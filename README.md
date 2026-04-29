# wazuh-email-alert (comunidade)

Objetivo: receber alerta JSON do Wazuh, renderizar e-mail HTML e enviar via `sendmail`.
Pré-requisito: o ambiente onde o script roda precisa ter um MTA compatível com `sendmail`. Neste guia, o MTA usado é o Postfix.
Se o `wazuh-manager` estiver em container, a recomendação é não rodar Postfix dentro dele. Use Postfix no host ou um relay SMTP externo.

## Como funciona na prática (Docker)

Neste modelo, o envio nativo de e-mail do Wazuh fica desativado para evitar duplicidade, e quem passa a enviar é a integração `custom-email-html`. Quando um alerta atinge o nível configurado no `ossec.conf`, o Wazuh chama o wrapper, o wrapper chama o `wazuh_html_mailer.py`, e o mailer renderiza o HTML com `templates/wazuh_alert_template.html` antes de entregar a mensagem para o `sendmail`.

Em ambiente containerizado, o ponto importante é que o container do `wazuh-manager` normalmente não tem MTA completo. Por isso, o fluxo recomendado é o container apenas encaminhar a mensagem para fora (host/relay), e o Postfix no host fazer o relay SMTP final para o provedor de e-mail.

No Postfix, você precisa configurar o remetente e a autenticação SMTP da conta usada para envio. Se o relay for Gmail/Google Workspace, use senha de aplicativo (App Password) da conta remetente (com 2FA habilitado), e não a senha normal da conta.

## Estrutura mínima

- `wazuh_html_mailer.py`
- `templates/wazuh_alert_template.html`
- `scripts/custom-email-html`

## Integração rápida no Wazuh Manager

1. Instale os 3 arquivos nos caminhos esperados pelo wrapper:

```bash
sudo install -m 750 scripts/custom-email-html /var/ossec/integrations/custom-email-html
sudo install -m 750 wazuh_html_mailer.py /var/ossec/wazuh_html_mailer.py
sudo mkdir -p /var/ossec/templates
sudo install -m 640 templates/wazuh_alert_template.html /var/ossec/templates/wazuh_alert_template.html
sudo chown root:wazuh /var/ossec/integrations/custom-email-html /var/ossec/wazuh_html_mailer.py /var/ossec/templates/wazuh_alert_template.html
```

2. Configure o `ossec.conf`:

```xml
<integration>
  <name>custom-email-html</name>
  <alert_format>json</alert_format>
  <level>10</level>
</integration>
```

3. Defina remetente/destinatário no serviço do manager:

```bash
sudo systemctl edit wazuh-manager
```

```ini
[Service]
Environment="WAZUH_MAIL_TO=soc@empresa.com"
Environment="WAZUH_MAIL_FROM=wazuh@empresa.com"
Environment="WAZUH_MAIL_SUBJECT_PREFIX=Wazuh Security Alert"
```

4. Reinicie serviços:

```bash
sudo systemctl daemon-reload
sudo systemctl restart wazuh-manager
sudo systemctl restart postfix
```

`postfix` só precisa ser reiniciado onde ele estiver rodando.

## Teste rápido (sem envio)

```bash
WAZUH_MAIL_NO_SEND=1 /var/ossec/integrations/custom-email-html /caminho/alerta.json
```
