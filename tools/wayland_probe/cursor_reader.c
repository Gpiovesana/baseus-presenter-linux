/* Disposable PipeWire consumer: cursor metadata only, never reads image pixels.
 * API reference: https://docs.pipewire.org/video-play_8c-example.html
 */
#include <errno.h>
#include <inttypes.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <unistd.h>
#include <pipewire/pipewire.h>
#include <spa/param/video/format-utils.h>
#include <spa/buffer/meta.h>
#include <spa/pod/builder.h>

struct probe {
    struct pw_main_loop *loop;
    struct pw_stream *stream;
    struct spa_hook listener;
    uint64_t buffers, cursor_buffers, valid_cursor_buffers, last_output;
    int error;
};

static uint64_t milliseconds(void) {
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    return (uint64_t)now.tv_sec * 1000 + now.tv_nsec / 1000000;
}

static void process(void *userdata) {
    struct probe *p = userdata;
    struct pw_buffer *buffer;
    while ((buffer = pw_stream_dequeue_buffer(p->stream)) != NULL) {
        p->buffers++;
        struct spa_meta_cursor *cursor = spa_buffer_find_meta_data(
            buffer->buffer, SPA_META_Cursor, sizeof(struct spa_meta_cursor));
        if (cursor) {
            p->cursor_buffers++;
            if (cursor->id != 0) {
                p->valid_cursor_buffers++;
                uint64_t now = milliseconds();
                /* Bound log volume, while counters include every received buffer. */
                if (now - p->last_output >= 100) {
                    printf("{\"event\":\"cursor\",\"time_ms\":%" PRIu64
                           ",\"id\":%u,\"x\":%d,\"y\":%d}\n",
                           now, cursor->id, cursor->position.x, cursor->position.y);
                    p->last_output = now;
                }
            }
        }
        pw_stream_queue_buffer(p->stream, buffer);
    }
}

static void format_changed(void *userdata, uint32_t id, const struct spa_pod *param) {
    struct probe *p = userdata;
    struct spa_video_info_raw info = {0};
    if (!param || id != SPA_PARAM_Format || spa_format_video_raw_parse(param, &info) < 0)
        return;
    printf("{\"event\":\"format\",\"width\":%u,\"height\":%u}\n", info.size.width, info.size.height);
    uint8_t storage[1024];
    struct spa_pod_builder builder = SPA_POD_BUILDER_INIT(storage, sizeof(storage));
    const struct spa_pod *params[1];
    /* Request cursor metadata explicitly, with space for the optional bitmap.
       Bitmap bytes are not read or persisted by this probe. */
    params[0] = spa_pod_builder_add_object(&builder,
        SPA_TYPE_OBJECT_ParamMeta, SPA_PARAM_Meta,
        SPA_PARAM_META_type, SPA_POD_Id(SPA_META_Cursor),
        SPA_PARAM_META_size, SPA_POD_CHOICE_RANGE_Int(
            sizeof(struct spa_meta_cursor) + sizeof(struct spa_meta_bitmap) + 64 * 64 * 4,
            sizeof(struct spa_meta_cursor) + sizeof(struct spa_meta_bitmap) + 1 * 1 * 4,
            /* Mutter 46.2 offers a fixed 384x384 metadata allocation. */
            sizeof(struct spa_meta_cursor) + sizeof(struct spa_meta_bitmap) + 384 * 384 * 4));
    pw_stream_update_params(p->stream, params, 1);
}

static void state_changed(void *userdata, enum pw_stream_state old,
                          enum pw_stream_state state, const char *error) {
    (void)old;
    struct probe *p = userdata;
    if (state == PW_STREAM_STATE_ERROR) {
        fprintf(stderr, "PipeWire stream error: %s\n", error ? error : "unknown");
        p->error = 1;
        pw_main_loop_quit(p->loop);
    }
}

static void core_error(void *userdata, uint32_t id, int seq, int res, const char *message) {
    (void)id; (void)seq; (void)res;
    struct probe *p = userdata;
    fprintf(stderr, "PipeWire core error: %s\n", message);
    p->error = 1;
    pw_main_loop_quit(p->loop);
}

static void quit(void *userdata, int signal_number) {
    (void)signal_number;
    pw_main_loop_quit(((struct probe *)userdata)->loop);
}

static const struct pw_stream_events events = {
    PW_VERSION_STREAM_EVENTS,
    .state_changed = state_changed,
    .param_changed = format_changed,
    .process = process,
};
static const struct pw_core_events core_events = { PW_VERSION_CORE_EVENTS, .error = core_error };

int main(int argc, char **argv) {
    if (argc != 3) {
        fprintf(stderr, "Usage: cursor-reader INHERITED_PORTAL_FD NODE_ID\n");
        return 2;
    }
    char *end;
    long fd = strtol(argv[1], &end, 10);
    if (*end || fd < 0 || fd > INT32_MAX) return 2;
    unsigned long node = strtoul(argv[2], &end, 10);
    if (*end || node >= UINT32_MAX) return 2;
    setvbuf(stdout, NULL, _IOLBF, 0);
    pw_init(&argc, &argv);
    struct probe p = {0};
    p.loop = pw_main_loop_new(NULL);
    if (!p.loop) return 1;
    /* Block signals before context creation so worker threads inherit the mask.
       Otherwise SIGTERM can kill a worker before the loop writes statistics. */
    pw_loop_add_signal(pw_main_loop_get_loop(p.loop), SIGINT, quit, &p);
    pw_loop_add_signal(pw_main_loop_get_loop(p.loop), SIGTERM, quit, &p);
    struct pw_context *context = pw_context_new(pw_main_loop_get_loop(p.loop), NULL, 0);
    struct pw_core *core = context ? pw_context_connect_fd(context, (int)fd, NULL, 0) : NULL;
    if (!core) {
        fprintf(stderr, "Cannot connect to portal PipeWire fd: %s\n", strerror(errno));
        if (context) pw_context_destroy(context);
        pw_main_loop_destroy(p.loop);
        pw_deinit();
        return 1;
    }
    struct spa_hook core_listener;
    pw_core_add_listener(core, &core_listener, &core_events, &p);
    p.stream = pw_stream_new(core, "Baseus cursor metadata probe",
        pw_properties_new(PW_KEY_MEDIA_TYPE, "Video", PW_KEY_MEDIA_CATEGORY, "Capture",
                          PW_KEY_MEDIA_ROLE, "Screen", NULL));
    if (!p.stream) {
        p.error = 1;
    } else {
        pw_stream_add_listener(p.stream, &p.listener, &events, &p);
        uint8_t storage[2048];
        struct spa_pod_builder builder = SPA_POD_BUILDER_INIT(storage, sizeof(storage));
        const struct spa_pod *params[1];
        params[0] = spa_pod_builder_add_object(&builder,
            SPA_TYPE_OBJECT_Format, SPA_PARAM_EnumFormat,
            SPA_FORMAT_mediaType, SPA_POD_Id(SPA_MEDIA_TYPE_video),
            SPA_FORMAT_mediaSubtype, SPA_POD_Id(SPA_MEDIA_SUBTYPE_raw),
            SPA_FORMAT_VIDEO_format, SPA_POD_CHOICE_ENUM_Id(5,
                SPA_VIDEO_FORMAT_BGRx, SPA_VIDEO_FORMAT_RGBx, SPA_VIDEO_FORMAT_BGRA,
                SPA_VIDEO_FORMAT_RGBA, SPA_VIDEO_FORMAT_BGRx),
            SPA_FORMAT_VIDEO_size, SPA_POD_CHOICE_RANGE_Rectangle(
                &SPA_RECTANGLE(1920,1080), &SPA_RECTANGLE(1,1), &SPA_RECTANGLE(16384,16384)),
            SPA_FORMAT_VIDEO_framerate, SPA_POD_CHOICE_RANGE_Fraction(
                &SPA_FRACTION(30,1), &SPA_FRACTION(0,1), &SPA_FRACTION(240,1)));
        int res = pw_stream_connect(p.stream, PW_DIRECTION_INPUT, (uint32_t)node,
                                   PW_STREAM_FLAG_AUTOCONNECT | PW_STREAM_FLAG_MAP_BUFFERS, params, 1);
        if (res < 0) {
            fprintf(stderr, "Cannot connect stream: %s\n", strerror(-res));
            p.error = 1;
        } else {
            pw_main_loop_run(p.loop);
        }
        pw_stream_destroy(p.stream);
    }
    printf("{\"event\":\"stats\",\"buffers\":%" PRIu64
           ",\"cursor_buffers\":%" PRIu64 ",\"valid_cursor_buffers\":%" PRIu64 "}\n",
           p.buffers, p.cursor_buffers, p.valid_cursor_buffers);
    spa_hook_remove(&core_listener);
    pw_core_disconnect(core);
    pw_context_destroy(context);
    pw_main_loop_destroy(p.loop);
    pw_deinit();
    return p.error;
}
