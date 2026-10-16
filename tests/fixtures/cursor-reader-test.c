/* Exercise the real consumer with synthetic SPA buffers; no compositor needed. */
#define main cursor_reader_main
#define pw_stream_dequeue_buffer fixture_dequeue
#define pw_stream_queue_buffer fixture_queue
#define pw_stream_update_params fixture_update_params
#include "../../tools/wayland_probe/cursor_reader.c"
#undef main
#undef pw_stream_dequeue_buffer
#undef pw_stream_queue_buffer
#undef pw_stream_update_params
#include <assert.h>
#include <spa/pod/filter.h>

int fixture_update_params(struct pw_stream *stream, const struct spa_pod **params,
                          uint32_t n_params) {
    (void)stream;
    assert(n_params == 1);
    /* Mutter 46.2 offers a fixed 384x384 cursor metadata block. Exercise the
       real SPA intersection, rather than comparing source constants. */
    uint8_t offered_storage[256], result_storage[1024];
    struct spa_pod_builder offered = SPA_POD_BUILDER_INIT(offered_storage, sizeof(offered_storage));
    struct spa_pod_builder result = SPA_POD_BUILDER_INIT(result_storage, sizeof(result_storage));
    const struct spa_pod *mutter = spa_pod_builder_add_object(&offered,
        SPA_TYPE_OBJECT_ParamMeta, SPA_PARAM_Meta,
        SPA_PARAM_META_type, SPA_POD_Id(SPA_META_Cursor),
        SPA_PARAM_META_size, SPA_POD_Int(
            sizeof(struct spa_meta_cursor) + sizeof(struct spa_meta_bitmap) + 384 * 384 * 4));
    struct spa_pod *intersection = NULL;
    assert(spa_pod_filter(&result, &intersection, params[0], mutter) >= 0);
    assert(intersection != NULL);
    return 0;
}

static struct pw_buffer *next_buffer;
static unsigned returned_buffers;
struct pw_buffer *fixture_dequeue(struct pw_stream *stream) {
    (void)stream;
    struct pw_buffer *buffer = next_buffer;
    next_buffer = NULL;
    return buffer;
}
int fixture_queue(struct pw_stream *stream, struct pw_buffer *buffer) {
    (void)stream; (void)buffer;
    returned_buffers++;
    return 0;
}
int main(void) {
    struct probe p = {0};
    struct spa_buffer spa = {0};
    struct pw_buffer buffer = { .buffer = &spa };
    next_buffer = &buffer;
    process(&p);
    assert(p.buffers == 1 && p.cursor_buffers == 0 && p.valid_cursor_buffers == 0);
    struct spa_meta_cursor cursor = { .id = 0, .position = SPA_POINT(123,456) };
    struct spa_meta meta = { .type = SPA_META_Cursor, .size = sizeof(cursor), .data = &cursor };
    spa.metas = &meta;
    spa.n_metas = 1;
    next_buffer = &buffer;
    process(&p);
    assert(p.cursor_buffers == 1 && p.valid_cursor_buffers == 0);
    cursor.id = 1;
    next_buffer = &buffer;
    process(&p);
    assert(p.cursor_buffers == 2 && p.valid_cursor_buffers == 1);
    assert(returned_buffers == 3);
    uint8_t storage[1024];
    struct spa_pod_builder builder = SPA_POD_BUILDER_INIT(storage, sizeof(storage));
    struct spa_video_info_raw info = {
        .format = SPA_VIDEO_FORMAT_BGRx, .size = SPA_RECTANGLE(1600, 900),
        .framerate = SPA_FRACTION(60, 1),
    };
    const struct spa_pod *format = spa_format_video_raw_build(&builder, SPA_PARAM_Format, &info);
    format_changed(&p, SPA_PARAM_Format, format);
    return 0;
}
