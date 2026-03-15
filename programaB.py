import socket
from datetime import datetime

def gerar_relatorio_hl7(dados_pedido):
    # Obter a data e hora atual no formato HL7 (YYYYMMDDHHMMSS)
    data_atual = datetime.now().strftime("%Y%m%d%H%M%S")
    
    # MSH-7: Data da mensagem | MSH-10: ID da mensagem
    msh = f"MSH|^~\\&|ProgB|LAB|ProgA|HOSPITAL|{data_atual}||ORU^R01|201|P|2.5"
    pid = "PID|1||12345||SILVA^JOAO"
    # OBR-7: Data/Hora da observação (emissão do resultado)
    obr = f"OBR|1|||RAD01^RAIO-X TORAX|||{data_atual}"
    # OBX: Resultado e observações
    obx = "OBX|1|ST|RAD01^RESULTADO||PULMOES LIMPOS. SEM ANOMALIAS.|Normal|||F"
    
    # Protocolo MLLP: <VT> no início, <FS><CR> no fim
    return f"\x0b{msh}\r{pid}\r{obr}\r{obx}\r\x1c\r"

def iniciar_servidor_exames(host='127.0.0.1', porta=6662):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, porta))
        s.listen()
        print(f"Programa B (Laboratório) ativo na porta {porta}...")
        print("A aguardar pedidos do Mirth Connect...")
        
        while True:
            conn, addr = s.accept()
            with conn:
                dados = conn.recv(4096)
                if dados:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] Pedido recebido. A gerar relatório...")
                    relatorio = gerar_relatorio_hl7(dados.decode('utf-8'))
                    conn.sendall(relatorio.encode('utf-8'))
                    print("Relatório enviado com sucesso.")

if __name__ == "__main__":
    iniciar_servidor_exames()