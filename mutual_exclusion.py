import socket
import threading
import time
import random
from datetime import datetime
from filelock import FileLock

# Configurações
PORT_BASE = 6000
NUM_DEVICES = 4
RESOURCE_FILE = "recurso.txt"
LOCK_FILE = "lockfile.lock"

# Cores ANSI 
RED = '\033[91m'
GREEN = '\033[92m'
YELLOW = '\033[93m'
RESET = '\033[0m'

class Device:
    """
    Classe que representa um dispositivo no sistema distribuído. 
    Cada dispositivo pode solicitar, acessar e liberar um recurso compartilhado, 
    respeitando as regras de exclusão mútua distribuída.
    """

    def __init__(self, device_id, num_devices):
        """
        Inicializa um dispositivo com um ID, define atributos para controle de acesso 
        ao recurso e inicia o servidor para receber solicitações.
        """
        self.device_id = device_id  # ID exclusivo do dispositivo
        self.num_devices = num_devices  # Número total de dispositivos
        self.lock = FileLock(LOCK_FILE)  # Bloqueio global para controlar o acesso ao recurso
        self.queue = []  # Fila para armazenar solicitações de outros dispositivos
        self.waiting_for_access = False  # Indica se o dispositivo está aguardando acesso
        self.using_resource = False  # Indica se o dispositivo está atualmente usando o recurso
        self.timestamp = None  # Timestamp da última solicitação de acesso
        self.received_permissions = 0  # Contador de permissões recebidas de outros dispositivos

        # Iniciar servidor em uma nova thread para escutar mensagens
        self.server = threading.Thread(target=self.start_server)
        self.server.start()

        # Aguarda para garantir que todos os servidores estejam prontos antes de iniciar
        time.sleep(5)

        # Inicia o loop para solicitar acesso ao recurso
        self.request_loop()

    def start_server(self):
        """
        Inicia um servidor TCP para receber solicitações de outros dispositivos.
        Aceita conexões e cria uma nova thread para processar cada mensagem recebida.
        """
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("0.0.0.0", PORT_BASE + self.device_id - 1))  # Escuta na porta designada
            s.listen()

            print(f"Escutando na porta {PORT_BASE + self.device_id - 1}...", flush=True)
            while True:
                conn, _ = s.accept()  # Aceita uma nova conexão
                threading.Thread(target=self.handle_request, args=(conn,)).start()  # Nova thread para lidar com a solicitação

    def handle_request(self, conn):
        """
        Processa as mensagens recebidas de outros dispositivos, identificando 
        se é uma solicitação de acesso, uma permissão ou uma liberação do recurso.
        """
        with conn:
            data = conn.recv(1024).decode()  # Recebe e decodifica a mensagem
            if data:
                parts = data.split(',')  # Divide a mensagem em partes
                command = parts[0]  # Extrai o comando (REQUEST, OK ou RELEASE)

                if command == "OK" and len(parts) == 2:
                    sender_id = int(parts[1])
                    self.received_permissions += 1  # Incrementa o contador de permissões
                    print(f"Recebeu OK do dispositivo {sender_id}", flush=True)
                
                elif len(parts) == 3:  # Mensagens do tipo "REQUEST" e "RELEASE" têm 3 partes
                    sender_id, timestamp = parts[1], parts[2]

                    try:
                        sender_id = int(sender_id)
                        timestamp = float(timestamp)

                        if command == "REQUEST":
                            self.handle_request_message(sender_id, timestamp)  # Lida com a solicitação de acesso
                        elif command == "RELEASE":
                            self.handle_release_message(sender_id)  # Lida com a liberação do recurso
                    except ValueError:
                        print(f"Erro ao converter valores da mensagem recebida: {data}", flush=True)
                else:
                    print(f"Mensagem malformada recebida: {data}", flush=True)

    def handle_request_message(self, sender_id, timestamp):
        """
        Lida com solicitações de acesso recebidas de outros dispositivos. 
        Verifica o estado atual (usando ou aguardando o recurso) e decide 
        se concede ou nega o acesso.
        """
        print(f"Requisição recebida de Dispositivo {sender_id}. Minha Fila: {[req[0] for req in self.queue]}", flush=True)
        
        if self.using_resource:
            # Caso 2: Este dispositivo está usando o recurso
            print(f"{RED}Acesso negado. Recurso em uso por Dispositivo {self.device_id}{RESET}", flush=True)
            self.queue.append((sender_id, timestamp))  # Adiciona a solicitação à fila
        elif self.waiting_for_access:
            # Caso 3: Este dispositivo também quer acessar o recurso
            if timestamp < self.timestamp or (timestamp == self.timestamp and sender_id < self.device_id):
                # O outro processo tem prioridade
                self.send_message(sender_id, "OK")
            else:
                # Este processo tem prioridade, nega o acesso
                print(f"{RED}Acesso negado. Timestamp recebido de Dispositivo {sender_id} ({timestamp}) é maior que o meu ({self.timestamp}){RESET}", flush=True)
                self.queue.append((sender_id, timestamp))  # Adiciona à fila
        else:
            # Caso 1: Não está usando o recurso e não quer usá-lo
            self.send_message(sender_id, "OK")
        
        # Exibe a fila atualizada após o recebimento da solicitação
        print(f"Fila atualizada: {[req[0] for req in self.queue]}", flush=True)

    def handle_release_message(self, sender_id):
        """
        Lida com a liberação do recurso, processando os dispositivos 
        na fila de espera e concedendo acesso a eles na ordem correta.
        """
        if self.queue:
            next_device, _ = self.queue.pop(0)  # Remove o próximo dispositivo da fila
            self.send_message(next_device, "OK")  # Envia permissão para o próximo dispositivo
        print(f"Fila após liberação: {[req[0] for req in self.queue]}", flush=True)

    def send_message(self, receiver_id, command):
        """
        Envia uma mensagem para outro dispositivo, lidando com possíveis erros de conexão 
        e fazendo até 5 tentativas de reconexão em caso de falha.
        """
        retries = 5
        while retries > 0:
            try:
                receiver_host = f"device{receiver_id}"  # Nome do host do dispositivo
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.connect((receiver_host, PORT_BASE + receiver_id - 1))  # Conecta ao dispositivo alvo
                    if command == "OK":
                        s.sendall(f"{command},{self.device_id}".encode())  # Envia mensagem de permissão
                    else:
                        s.sendall(f"{command},{self.device_id},{self.timestamp}".encode())  # Envia solicitação de acesso
                break  # Sai do loop se a mensagem foi enviada com sucesso
            except (ConnectionRefusedError, BrokenPipeError) as e:
                print(f"Falha ao conectar ou enviar para dispositivo {receiver_id} ({str(e)}), tentando novamente...", flush=True)
                time.sleep(1)
                retries -= 1  # Diminui o número de tentativas restantes
            except Exception as e:
                print(f"Erro inesperado ao se comunicar com dispositivo {receiver_id}: {str(e)}", flush=True)
                break

    def request_access(self):
        """
        Solicita acesso ao recurso, enviando mensagens "REQUEST" para todos os 
        outros dispositivos e aguardando permissões para acessar o recurso.
        """
        self.waiting_for_access = True
        self.timestamp = time.time()  # Marca o timestamp da solicitação
        self.received_permissions = 0  # Reseta o contador de permissões

        print(f"{YELLOW}Solicitando acesso ao recurso...{RESET}", flush=True)

        # Envia uma solicitação de acesso para todos os dispositivos, exceto ele mesmo
        for i in range(1, self.num_devices + 1):
            if i != self.device_id:
                self.send_message(i, "REQUEST")

        # Aguarda receber permissões de todos os outros dispositivos
        while self.received_permissions < self.num_devices - 1:
            time.sleep(0.1)  # Pequeno atraso para evitar loop excessivo

        # Quando todas as permissões são recebidas, acessa o recurso
        self.access_resource()

    def access_resource(self):
        """
        Acessa o recurso compartilhado com exclusão mútua, escreve um registro no arquivo, 
        mantém o acesso por 10 segundos e depois libera o recurso.
        """
        with self.lock:  # Adquire o bloqueio global do recurso
            self.using_resource = True  # Marca que o recurso está em uso por este dispositivo
            print(f"{GREEN}Acesso permitido. Acessando o recurso...{RESET}", flush=True)
            with open(RESOURCE_FILE, "a") as f:
                f.write(f"Dispositivo {self.device_id} acessou em {datetime.now()}\n")
                f.flush()  # Garante que os dados sejam gravados imediatamente
            time.sleep(10)  # Simula o uso do recurso por 10 segundos

        # Libera o recurso e processa a fila de solicitações pendentes
        self.using_resource = False
        for _ in range(len(self.queue)):
            self.handle_release_message(None)
        self.waiting_for_access = False

    def request_loop(self):
        """
        Loop contínuo que solicita acesso ao recurso em intervalos aleatórios 
        entre 5 e 15 segundos.
        """
        while True:
            time.sleep(random.randint(5, 15))  # Aguarda por um intervalo aleatório
            self.request_access()  # Solicita acesso ao recurso

if __name__ == "__main__":
    import sys
    device_id = int(sys.argv[1]) if len(sys.argv) > 1 else 1  # Obtém o ID do dispositivo a partir dos argumentos
    Device(device_id, NUM_DEVICES)  # Inicializa o dispositivo
