#!/usr/bin/env python3
"""
Verifica a fiação dos pyqtSignal da aplicação — versão que resolve
"uso interno" com a MESMA precisão por classe usada pro composition root,
em vez de casar por nome de sinal solto.

Reconhece dois padrões de instanciação:
    var = Classe(...)              (composition root, nível de módulo)
    self.var = Classe(...)         (dentro do __init__ de qualquer classe)

E dois padrões de conexão:
    var.sinal.connect(...)
    self.var.sinal.connect(...)
    self.sinal.connect(...)        (uma classe conectando o PRÓPRIO sinal,
                                     ex: dentro dela mesma)

Não importa nem executa o projeto — só AST. Roda sem PyQt5/evdev/vosk.

Uso:
    python3 tools/check_signals.py
"""
import ast
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
APP_DIR = PROJECT_ROOT / "app"
COMPOSITION_ROOT = PROJECT_ROOT / "baseus_app.py"


class FileAnalyzer(ast.NodeVisitor):
    """Um visitor por arquivo. Sabe em qual classe está no momento, então
    resolve 'self.X' e 'self' corretamente, sem precisar de heurística
    baseada só em nome de variável solta."""

    def __init__(self, filename):
        self.filename = filename
        self.signals = []            # (classe, sinal, linha)
        self.connections = []        # (classe_resolvida_ou_None, sinal, linha)
        self.plain_vars = {}         # var -> classe   (nível de módulo/função)
        self.self_attrs = {}         # {classe: {attr: classe_instanciada}}
        self._class_stack = []

    def _current_class(self):
        return self._class_stack[-1] if self._class_stack else None

    def visit_ClassDef(self, node):
        self._class_stack.append(node.name)
        self.self_attrs.setdefault(node.name, {})

        for stmt in node.body:
            if isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Call):
                func = stmt.value.func
                func_name = getattr(func, "id", getattr(func, "attr", None))
                if func_name == "pyqtSignal":
                    for target in stmt.targets:
                        if isinstance(target, ast.Name):
                            self.signals.append((node.name, target.id, stmt.lineno))

        self.generic_visit(node)
        self._class_stack.pop()

    def visit_Assign(self, node):
        if isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name):
            class_name = node.value.func.id
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self.plain_vars[target.id] = class_name
                elif (isinstance(target, ast.Attribute)
                      and isinstance(target.value, ast.Name)
                      and target.value.id == "self"
                      and self._current_class()):
                    self.self_attrs[self._current_class()][target.attr] = class_name
        self.generic_visit(node)

    def _resolve_owner(self, expr):
        """Dado o 'X' de 'X.sinal.connect(...)', descobre de qual classe é
        instância. Retorna None se não conseguir resolver com segurança
        (nunca inventa um palpite errado, só admite que não sabe)."""
        current = self._current_class()
        if isinstance(expr, ast.Name):
            if expr.id == "self" and current:
                return current
            return self.plain_vars.get(expr.id)
        if (isinstance(expr, ast.Attribute)
                and isinstance(expr.value, ast.Name)
                and expr.value.id == "self"
                and current):
            return self.self_attrs.get(current, {}).get(expr.attr)
        return None

    def visit_Call(self, node):
        if isinstance(node.func, ast.Attribute) and node.func.attr == "connect":
            signal_expr = node.func.value
            if isinstance(signal_expr, ast.Attribute):
                signal_name = signal_expr.attr
                owner_class = self._resolve_owner(signal_expr.value)
                self.connections.append((owner_class, signal_name, node.lineno))
        self.generic_visit(node)


def analyze(py_file: Path) -> FileAnalyzer:
    analyzer = FileAnalyzer(py_file.name)
    try:
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    except SyntaxError as exc:
        print(f"⚠️  Não consegui analisar {py_file}: {exc}")
        return analyzer
    analyzer.visit(tree)
    return analyzer


def main():
    if not APP_DIR.exists():
        print(f"❌ Pasta de módulos não encontrada em {APP_DIR}")
        return 1
    if not COMPOSITION_ROOT.exists():
        print(f"❌ Composition root não encontrado em {COMPOSITION_ROOT}")
        return 1

    app_files = sorted(APP_DIR.glob("*.py"))
    module_analyses = [analyze(f) for f in app_files]
    root_analysis = analyze(COMPOSITION_ROOT)

    all_signals = []          # (classe, sinal, arquivo, linha)
    for a in module_analyses:
        for cls, sig, line in a.signals:
            all_signals.append((cls, sig, a.filename, line))
    declared = {(cls, sig) for cls, sig, _, _ in all_signals}

    # Conexões resolvidas por classe, separadas por "onde" (público vs interno)
    public_connected = {(cls, sig) for cls, sig, _ in root_analysis.connections if cls}
    internal_connected = set()
    for a in module_analyses:
        for cls, sig, _ in a.connections:
            if cls:
                internal_connected.add((cls, sig))

    # --- checagem reversa: conexão no composition root apontando pra sinal
    #     que não existe (typo ou sinal removido) ---
    invalid = [
        (cls, sig, line) for cls, sig, line in root_analysis.connections
        if cls and (cls, sig) not in declared
    ]

    print(f"🔎 {len(all_signals)} sinal(is) declarado(s) em {len(app_files)} módulo(s).\n")

    grouped = {}
    for cls, sig, fname, line in all_signals:
        grouped.setdefault(cls, []).append((sig, fname, line))

    orphans = []
    for cls, sigs in sorted(grouped.items()):
        print(f"  {cls}")
        for sig, fname, line in sigs:
            key = (cls, sig)
            if key in public_connected:
                print(f"    ✓ {sig}  → Composition Root")
            elif key in internal_connected:
                print(f"    ✓ {sig}  → uso interno (verificado por classe)")
            else:
                print(f"    ❌ {sig}  → SEM CONEXÃO")
                orphans.append((cls, sig, fname, line))
        print()

    print("────────────────────────────────────────")
    ok = True

    if orphans:
        ok = False
        print(f"🚨 {len(orphans)} sinal(is) declarado(s) sem NENHUMA conexão (nem pública, nem interna):")
        for cls, sig, fname, line in orphans:
            print(f"   {fname}:{line}   {cls}.{sig}")
        print()

    if invalid:
        ok = False
        print(f"🚨 {len(invalid)} conexão(ões) no {COMPOSITION_ROOT.name} apontando pra sinal inexistente:")
        for cls, sig, line in invalid:
            print(f"   {COMPOSITION_ROOT.name}:{line}   {cls}.{sig} (não declarado em nenhuma classe)")
        print()

    if ok:
        print("✅ Toda a fiação bate: nenhum sinal órfão, nenhuma conexão pendurada.")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())