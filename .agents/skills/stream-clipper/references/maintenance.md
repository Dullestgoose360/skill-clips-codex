# Manutenção da skill pessoal

A fonte de verdade é .agents/skills/stream-clipper/ no repositório Dullestgoose360/skill-clips-codex, branch codex/general-clipper-adaptation. A instalação pessoal é uma cópia verificada dessa pasta; não edite scripts na instalação.

## Remotes e branch

No checkout local, confirme os remotes antes de sincronizar:

~~~bash
git remote -v
~~~

O arranjo esperado é:

- origin → https://github.com/Dullestgoose360/skill-clips-codex.git
- upstream → https://github.com/davixavier-coder/skill-clips.git

Se estiver ausente, adicione sem sobrescrever remotes existentes:

~~~bash
git remote add origin https://github.com/Dullestgoose360/skill-clips-codex.git
git remote add upstream https://github.com/davixavier-coder/skill-clips.git
~~~

Se o nome já estiver ocupado por outra URL, não altere automaticamente; inspecione antes. Faça alterações na branch codex/general-clipper-adaptation, nunca diretamente na main.

## Sincronizar alterações do fork para a instalação

### Windows PowerShell

~~~powershell
$repo = (Get-Location).Path
$skill = Join-Path $repo ".agents\skills\stream-clipper"
$destination = Join-Path $HOME ".agents\skills\stream-clipper"

git status --short
git switch codex/general-clipper-adaptation
git pull --ff-only origin codex/general-clipper-adaptation

py -3.11 "$skill\scripts\install.py" --source "$skill" --destination "$destination"
& "$destination\.venv\Scripts\python.exe" -m pip install -r "$destination\requirements.txt"
& "$destination\.venv\Scripts\python.exe" "$destination\scripts\install.py" --verify --destination "$destination"
& "$destination\.venv\Scripts\python.exe" "$destination\scripts\clip.py" doctor
~~~

A sincronização cria uma pasta irmã com sufixo .backup-... antes de substituir a instalação existente. O backup inclui os arquivos anteriores e alterações locais; o ambiente virtual, o cache de modelos e runtime.json são preservados por cópia para a nova instalação. A cópia desses dados pode consumir espaço e tempo adicionais.

### macOS/Linux

~~~bash
git status --short
git switch codex/general-clipper-adaptation
git pull --ff-only origin codex/general-clipper-adaptation

SKILL="$PWD/.agents/skills/stream-clipper"
DEST="$HOME/.agents/skills/stream-clipper"
python3 "$SKILL/scripts/install.py" --source "$SKILL" --destination "$DEST"
"$DEST/.venv/bin/python" -m pip install -r "$DEST/requirements.txt"
"$DEST/.venv/bin/python" "$DEST/scripts/install.py" --verify --destination "$DEST"
"$DEST/.venv/bin/python" "$DEST/scripts/clip.py" doctor
~~~

A instalação não modifica ~/.codex/config.toml nem outras configurações globais do Codex.

## Verificar a instalação

O comando install.py --verify compara o manifesto SHA-256 registrado no recibo com os arquivos presentes na instalação. Ele confirma integridade da cópia, não reconhecimento pelo Codex.

Para confirmar o reconhecimento:

1. Feche e reabra o Codex depois da instalação.
2. Abra um diretório de trabalho fora do clone do repositório.
3. Consulte a lista de skills disponíveis no Codex ou invoque $stream-clipper.
4. Execute doctor usando o caminho absoluto da instalação.
5. Verifique que os caminhos exibidos apontam para ~/.agents/skills/stream-clipper, e não para o clone de desenvolvimento.

A confirmação visual do inventário e a invocação precisam ocorrer no Codex instalado no computador do usuário. Não considere apenas a existência da pasta como prova de reconhecimento.

## Rollback

O instalador imprime o caminho exato do backup criado. Não escolha um backup por aproximação: confira o horário e o conteúdo.

Windows:

~~~powershell
$destination = Join-Path $HOME ".agents\skills\stream-clipper"
$backup = "C:\Users\SEU_USUARIO\.agents\skills\stream-clipper.backup-AAAA..."
py -3.11 "$destination\scripts\install.py" --rollback "$backup" --destination "$destination"
~~~

macOS/Linux:

~~~bash
DEST="$HOME/.agents/skills/stream-clipper"
BACKUP="$HOME/.agents/skills/stream-clipper.backup-AAAA..."
python3 "$DEST/scripts/install.py" --rollback "$BACKUP" --destination "$DEST"
~~~

O rollback move a instalação atual para uma pasta irmã .rollback-retained-... e restaura o backup solicitado. Não apaga automaticamente nenhuma das duas versões. Se o comando falhar, não remova pastas manualmente; preserve os dados e investigue a mensagem.

## Sincronizar com o upstream

O upstream pode mudar, e a licença de origem precisa ser verificada novamente. Antes de incorporar qualquer commit:

~~~bash
git fetch upstream
git log --oneline --left-right HEAD...upstream/main
git diff --stat HEAD...upstream/main
git diff HEAD...upstream/main -- README.md SKILL.md scripts/
~~~

Não faça merge ou rebase automático. Revise licença, mudanças de código e impacto na skill Codex. Preserve a versão de origem auditada e registre novo SHA e decisões em docs/ORIGIN-AUDIT.md. Integre somente alterações autorizadas e compatíveis, em commits pequenos na branch de desenvolvimento.

## Segurança operacional

- Não grave tokens, cookies ou URLs assinadas em arquivos versionados.
- Não coloque .venv, cache de modelos, mídia ou runtime.json no Git.
- Não limpe backups nem caches automaticamente.
- Não atualize a pasta pessoal enquanto o Codex estiver executando uma análise.
- A instalação preserva backup para rollback; verifique espaço em disco antes de atualizar ambientes/modelos grandes.
