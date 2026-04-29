# wazuh-email-alert

Projeto para receber um alerta JSON do Wazuh, renderizar esse alerta em um template HTML e enviar o resultado por e-mail usando uma integração customizada.

O objetivo principal é substituir o envio nativo de e-mail do Wazuh por um envio mais flexível, permitindo customizar o layout do alerta, o assunto, o remetente, os destinatários e a lógica de filtragem antes do disparo.

> Ambiente usado como referência neste guia: Wazuh Manager rodando em Docker, com Postfix instalado no host Ubuntu e fazendo relay SMTP para Gmail/Google Workspace.

---

## Visão geral do fluxo

```text
Alerta gerado pelo Wazuh
  -> Wazuh Integrator verifica o bloco <integration>
  -> custom-email-html recebe o JSON do alerta
  -> custom-email-html chama wazuh_html_mailer.py
  -> wazuh_html_mailer.py renderiza templates/wazuh_alert_template.html
  -> wazuh_html_mailer.py entrega a mensagem para /usr/sbin/sendmail
  -> sendmail-shim encaminha a mensagem para host.docker.internal:25
  -> Postfix no host recebe a mensagem
  -> Postfix autentica no relay SMTP externo
  -> Gmail/Google Workspace entrega o e-mail final
```

Neste modelo, o e-mail nativo do Wazuh deve ficar desativado para evitar envio duplicado. Quem envia os alertas é a integração customizada.

A ideia é deixar o container do Wazuh responsável apenas por gerar e entregar a mensagem para o host. O envio real para a internet fica com o Postfix do host.

---

## Estrutura do projeto

```text
wazuh-email-alert/
├── README.md
├── wazuh_html_mailer.py
├── scripts/
│   ├── custom-email-html
│   └── sendmail-shim
└── templates/
    └── wazuh_alert_template.html
```

Para ambiente Docker, os arquivos devem ser copiados ou montados em uma pasta persistente no host, por exemplo:

```text
./config/custom-integrations/
├── custom-email-html
├── sendmail-shim
├── wazuh_html_mailer.py
└── templates/
    └── wazuh_alert_template.html
```

---

## Pré-requisitos

No host Ubuntu:

```bash
sudo apt update
sudo apt install -y postfix mailutils libsasl2-modules ca-certificates
```

Durante a instalação do Postfix, para um cenário simples de relay, normalmente você pode escolher:

```text
Internet Site
```

Depois, a configuração principal será ajustada manualmente em `/etc/postfix/main.cf`.

Você também precisa de uma conta de e-mail válida para autenticar no provedor SMTP. Se usar Gmail ou Google Workspace, normalmente será necessário habilitar 2FA na conta e gerar uma senha de aplicativo. Não use a senha normal da conta no `sasl_passwd`.

---

## Configuração do Postfix no host

O Postfix será o transporte SMTP do host. Ele precisa fazer duas coisas:

1. aceitar conexões vindas do container do Wazuh;
2. encaminhar os e-mails para o provedor SMTP externo.

Edite o arquivo:

```bash
sudo nano /etc/postfix/main.cf
```

Uma configuração base para Gmail/Google Workspace é:

```conf
# =========================
# Identidade local
# =========================
myhostname = wazuh-host
mydestination = $myhostname, localhost.localdomain, localhost
alias_maps = hash:/etc/aliases
alias_database = hash:/etc/aliases

# =========================
# Interfaces
# =========================
inet_interfaces = all
inet_protocols = all

# =========================
# TLS
# =========================
smtp_tls_CApath = /etc/ssl/certs
smtp_tls_CAfile = /etc/ssl/certs/ca-certificates.crt
smtp_tls_security_level = encrypt
smtp_tls_session_cache_database = btree:${data_directory}/smtp_scache
smtp_use_tls = yes

# =========================
# Relay externo
# =========================
relayhost = [smtp.gmail.com]:587
smtp_sasl_auth_enable = yes
smtp_sasl_password_maps = hash:/etc/postfix/sasl_passwd
smtp_sasl_security_options = noanonymous

# =========================
# Permissão de relay local/Docker
# =========================
# 127.0.0.0/8   = localhost IPv4
# [::1]/128     = localhost IPv6
# 172.16.0.0/12 = redes privadas normalmente usadas pelo Docker
mynetworks = 127.0.0.0/8 [::1]/128 172.16.0.0/12
smtpd_relay_restrictions = permit_mynetworks, reject_unauth_destination

# =========================
# Configurações gerais
# =========================
mailbox_size_limit = 0
recipient_delimiter = +
```

Crie o arquivo de autenticação SMTP:

```bash
sudo nano /etc/postfix/sasl_passwd
```

Conteúdo:

```text
[smtp.gmail.com]:587 email-remetente@dominio.com:senha_de_app
```

Ajuste permissões e gere o mapa do Postfix:

```bash
sudo chmod 600 /etc/postfix/sasl_passwd
sudo postmap /etc/postfix/sasl_passwd
sudo systemctl restart postfix
```

Verifique se o Postfix está ouvindo na porta 25:

```bash
sudo ss -ltnp | grep ':25'
```

Resultado esperado:

```text
LISTEN ... 0.0.0.0:25
LISTEN ... [::]:25
```

> Observação: se o relay for Gmail/Google Workspace, o remetente configurado no script deve ser compatível com a conta autenticada. Para usar um alias como remetente, ele precisa estar permitido/configurado no provedor da conta.

---

## Integração no Wazuh Manager Docker

### 1. Criar diretório persistente no host

Exemplo usando o diretório do `single-node` do Wazuh Docker:

```bash
cd /caminho/para/wazuh-docker/single-node
mkdir -p config/custom-integrations/templates
```

Copie os arquivos do projeto:

```bash
cp ./wazuh_html_mailer.py \
  /caminho/para/wazuh-docker/single-node/config/custom-integrations/wazuh_html_mailer.py

cp ./scripts/custom-email-html \
  /caminho/para/wazuh-docker/single-node/config/custom-integrations/custom-email-html

cp ./scripts/sendmail-shim \
  /caminho/para/wazuh-docker/single-node/config/custom-integrations/sendmail-shim

cp ./templates/wazuh_alert_template.html \
  /caminho/para/wazuh-docker/single-node/config/custom-integrations/templates/wazuh_alert_template.html
```

### 2. Posicionar o sendmail-shim

Como o container do Wazuh Manager normalmente não possui `/usr/sbin/sendmail`, use um shim para encaminhar a mensagem para o Postfix do host.

Garanta que o arquivo esteja neste caminho no host:

```bash
/caminho/para/wazuh-docker/single-node/config/custom-integrations/sendmail-shim
```

Permissão:

```bash
chmod +x /caminho/para/wazuh-docker/single-node/config/custom-integrations/sendmail-shim
```

### 3. Ajustar permissões dos arquivos

```bash
cd /caminho/para/wazuh-docker/single-node

WAZUH_GID="$(sudo docker exec single-node-wazuh.manager-1 getent group wazuh | cut -d: -f3)"

sudo chown root:"$WAZUH_GID" config/custom-integrations/custom-email-html
sudo chown root:"$WAZUH_GID" config/custom-integrations/wazuh_html_mailer.py
sudo chown root:"$WAZUH_GID" config/custom-integrations/sendmail-shim
sudo chown -R root:"$WAZUH_GID" config/custom-integrations/templates

sudo chmod 750 config/custom-integrations/custom-email-html
sudo chmod 640 config/custom-integrations/wazuh_html_mailer.py
sudo chmod 755 config/custom-integrations/sendmail-shim
sudo chmod -R 750 config/custom-integrations/templates
```

### 4. Ajustar o docker-compose.yml

No serviço `wazuh.manager`, adicione ou ajuste:

```yaml
environment:
  - WAZUH_SMTP_HOST=host.docker.internal
  - WAZUH_SMTP_PORT=25
  - WAZUH_MAIL_TO=soc@empresa.com
  - WAZUH_MAIL_FROM=wazuh@empresa.com
  - WAZUH_MAIL_SUBJECT_PREFIX=Wazuh Security Alert

extra_hosts:
  - "host.docker.internal:host-gateway"

volumes:
  - ./config/custom-integrations/custom-email-html:/var/ossec/integrations/custom-email-html:ro
  - ./config/custom-integrations/wazuh_html_mailer.py:/var/ossec/integrations/wazuh_html_mailer.py:ro
  - ./config/custom-integrations/templates:/var/ossec/integrations/templates:ro
  - ./config/custom-integrations/sendmail-shim:/usr/sbin/sendmail:ro
```

Não monte a pasta inteira em `/var/ossec/integrations`, porque isso pode sobrescrever ou esconder integrações padrão do Wazuh. Monte apenas os arquivos necessários.

Valide o Compose:

```bash
sudo docker compose config >/tmp/wazuh-compose-rendered.yml && echo OK
```

Recrie o manager:

```bash
sudo docker compose up -d --force-recreate wazuh.manager
```

---

## Configuração do Wazuh

Edite o arquivo de configuração do manager. No Wazuh Docker single-node, normalmente ele fica em algo parecido com:

```bash
nano ./config/wazuh_cluster/wazuh_manager.conf
```

No bloco `<global>`, deixe o e-mail nativo desativado:

```xml
<global>
  <email_notification>no</email_notification>
</global>
```

Adicione a integração customizada:

```xml
<integration>
  <name>custom-email-html</name>
  <level>12</level>
  <alert_format>json</alert_format>
</integration>
```

Neste exemplo, somente alertas de nível 12 ou superior chamam a integração.

Teste a configuração:

```bash
sudo docker exec -it single-node-wazuh.manager-1 bash -lc '/var/ossec/bin/wazuh-analysisd -t'
```

Reinicie o manager:

```bash
sudo docker compose restart wazuh.manager
```

---

## Ajustando destinatário, remetente e assunto

Uma das formas é passar as variáveis pelo `docker-compose.yml`:

```yaml
environment:
  - WAZUH_MAIL_TO=soc@empresa.com
  - WAZUH_MAIL_FROM=wazuh@empresa.com
  - WAZUH_MAIL_SUBJECT_PREFIX=Wazuh Security Alert
```

Também é possível deixar esses valores fixos dentro do wrapper `custom-email-html`, usando variáveis como:

```bash
TO_ADDR="soc@empresa.com"
FROM_ADDR="wazuh@empresa.com"
SUBJECT_PREFIX="Wazuh Security Alert"
```

Para produção, o ideal é usar um remetente válido e um destinatário de grupo, por exemplo:

```text
wazuh@empresa.com
soc-alertas@empresa.com
```

Assim, o gerenciamento de quem recebe os alertas fica no provedor de e-mail, e não dentro do script.

---

## Testes

### Verificar arquivos dentro do container

```bash
sudo docker exec -it single-node-wazuh.manager-1 bash -lc '
ls -lah /var/ossec/integrations/custom-email-html
ls -lah /var/ossec/integrations/wazuh_html_mailer.py
ls -lah /var/ossec/integrations/templates
ls -lah /usr/sbin/sendmail
'
```

### Testar resolução do host

```bash
sudo docker exec -it single-node-wazuh.manager-1 bash -lc 'getent hosts host.docker.internal'
```

### Testar SMTP do container até o Postfix

```bash
sudo docker exec -it single-node-wazuh.manager-1 bash -lc '
cat << "MAIL" | /usr/sbin/sendmail -t
From: wazuh@empresa.com
To: soc@empresa.com
Subject: Teste sendmail shim Wazuh

Teste enviado do container Wazuh via sendmail-shim.
MAIL
'
```

No host, acompanhe o log do Postfix:

```bash
sudo tail -n 50 /var/log/mail.log
```

Procure por algo como:

```text
status=sent
relay=smtp.gmail.com[...]:587
```

### Testar integração sem enviar e-mail

```bash
sudo docker exec -it single-node-wazuh.manager-1 bash -lc '
tail -n 1 /var/ossec/logs/alerts/alerts.json > /tmp/test-alert.json
WAZUH_MAIL_NO_SEND=1 /var/ossec/integrations/custom-email-html /tmp/test-alert.json
'
```

### Testar integração enviando e-mail real

```bash
sudo docker exec -it single-node-wazuh.manager-1 bash -lc '
tail -n 1 /var/ossec/logs/alerts/alerts.json > /tmp/test-alert.json
/var/ossec/integrations/custom-email-html /tmp/test-alert.json
'
```

---

## Persistência após recriar o container

Como os arquivos são montados a partir do host, eles continuam existindo mesmo após recriar o container.

Teste:

```bash
cd /caminho/para/wazuh-docker/single-node

sudo docker compose down
sudo docker compose up -d
sleep 10

sudo docker exec -it single-node-wazuh.manager-1 bash -lc '
ls -lah /var/ossec/integrations/custom-email-html
ls -lah /var/ossec/integrations/wazuh_html_mailer.py
ls -lah /var/ossec/integrations/templates
ls -lah /usr/sbin/sendmail
getent hosts host.docker.internal
'
```

Se os arquivos aparecerem e `host.docker.internal` resolver, a integração está persistente.

---

## Troubleshooting

### O container não consegue conectar no Postfix

Verifique se o Postfix está ouvindo em todas as interfaces:

```bash
sudo ss -ltnp | grep ':25'
```

Confira se o `main.cf` tem:

```conf
inet_interfaces = all
mynetworks = 127.0.0.0/8 [::1]/128 172.16.0.0/12
```

Depois reinicie:

```bash
sudo systemctl restart postfix
```

### O Postfix recusa relay

Verifique se a rede do container está dentro de `mynetworks`:

```bash
sudo docker inspect single-node-wazuh.manager-1 | grep -i IPAddress
```

Se necessário, ajuste `mynetworks` para incluir a rede Docker correta.

### O Gmail/Google Workspace rejeita autenticação

Confirme que você usou uma senha de aplicativo no `/etc/postfix/sasl_passwd`:

```text
[smtp.gmail.com]:587 email-remetente@dominio.com:senha_de_app
```

Depois rode novamente:

```bash
sudo postmap /etc/postfix/sasl_passwd
sudo systemctl restart postfix
```

### O e-mail chega como remetente errado

O `FROM_ADDR` ou `WAZUH_MAIL_FROM` precisa ser compatível com a conta autenticada no relay SMTP. Se quiser usar alias, configure e valide esse alias no provedor de e-mail antes.

### O Wazuh não chama a integração

Verifique:

```xml
<integration>
  <name>custom-email-html</name>
  <level>12</level>
  <alert_format>json</alert_format>
</integration>
```

E confira se o alerta testado possui nível igual ou maior que o configurado.

---
