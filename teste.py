# ~/Documentos/Projetos/baseus-presenter-linux/teste.py
from app.logger import get_logger
from app.config import load_config, save_config

# Puxa o logger com um nome de teste
log = get_logger("MeuTeste")

log.info("🚀 Iniciando o teste da Versão 2.0...")

# Testa se o config.py consegue ler o JSON e usar o logger internamente
log.info("Tentando carregar as configurações...")
configuracao = load_config()

# Mostra um valor na tela só pra confirmar
tamanho_laser = configuracao["visual"]["laser_size"]
log.debug(f"O tamanho atual do laser no JSON é: {tamanho_laser}")

log.info("✅ Teste finalizado com sucesso! Tudo funcionando perfeitamente.")
