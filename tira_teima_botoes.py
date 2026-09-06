import sys
from PyQt5.QtCore import QCoreApplication
from app.hardware import HardwareReader

app = QCoreApplication(sys.argv)
reader = HardwareReader()

print("\n--- Soro da Verdade Baseus ---")
print("1. Aperte o botão de GRAVAR (Microfone) umas 3 vezes.")
print("2. Depois, aperte o botão de TRADUZIR (Legendas) umas 3 vezes.")
print("Pressione Ctrl+C para sair.\n")

reader.record_toggled.connect(lambda s: print(f"SINAL ENVIADO: record_toggled -> {s}"))
reader.translate_toggled.connect(lambda s: print(f"SINAL ENVIADO: translate_toggled -> {s}"))

reader.start()
sys.exit(app.exec_())
