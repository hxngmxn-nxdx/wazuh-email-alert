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

## Integração rápida no Wazuh Manager (Docker)

1. Deixe os arquivos persistentes no host (exemplo: `./config/custom-integrations/`), e nao edite esses arquivos dentro do container.

2. No `docker-compose.yml`, monte os arquivos no `wazuh.manager` e defina as variaveis no proprio Compose (nao via `export` dentro do container):

```yaml
environment:
  - WAZUH_MAIL_TO=soc@empresa.com
  - WAZUH_MAIL_FROM=wazuh@empresa.com
  - WAZUH_MAIL_SUBJECT_PREFIX=Wazuh Security Alert

volumes:
  - ./config/custom-integrations/custom-email-html:/var/ossec/integrations/custom-email-html:ro
  - ./config/custom-integrations/wazuh_html_mailer.py:/var/ossec/wazuh_html_mailer.py:ro
  - ./config/custom-integrations/templates/wazuh_alert_template.html:/var/ossec/templates/wazuh_alert_template.html:ro
```

Opcao alternativa: voce pode deixar remetente/destinatario hardcoded no proprio `scripts/custom-email-html` (campos `TO_ADDR`, `FROM_ADDR` e `SUBJECT_PREFIX`) e nao definir `WAZUH_MAIL_*` no Compose. Mesmo nesse modelo, mantenha os scripts/template persistentes no host e montados por bind mount.

3. No `ossec.conf` do manager, desative e-mail nativo e mantenha a integracao customizada:

```xml
<global>
  <email_notification>no</email_notification>
</global>

<integration>
  <name>custom-email-html</name>
  <alert_format>json</alert_format>
  <level>10</level>
</integration>
```

4. Recrie o container do manager para aplicar:

```bash
docker compose up -d --force-recreate wazuh.manager
```

`postfix` deve ser reiniciado apenas no host/servico onde ele estiver rodando.

## Teste rápido (sem envio)

```bash
WAZUH_MAIL_NO_SEND=1 /var/ossec/integrations/custom-email-html /caminho/alerta.json
```
