# Stream Clipper — skill nativa do Codex

Fork independente de davixavier-coder/skill-clips, adaptado para o Codex e generalizado para vídeos longos, podcasts e transmissões gravadas. O fluxo ativo está em **.agents/skills/stream-clipper/**.

- **Descoberta:** busca automatizada inicial no YouTube; para Twitch e Kick, use links diretos ou descoberta externa.
- **Fontes:** VODs públicos finalizados e arquivos locais. Lives em andamento, fontes privadas, DRM, conteúdo exclusivo para membros e tentativas de contornar autenticação não são suportados.
- **Análise:** transcrição local em blocos, indicadores de áudio, tentativa de chat replay do YouTube e seleção editorial feita pelo Codex.
- **Revisão:** candidatos e previews são apresentados antes da aprovação explícita.
- **Exportação:** FFmpeg gera 9:16, 16:9 ou 1:1, com legendas e layout configurável.
- **Publicação:** não existe publicação automática neste projeto.

## Estrutura

~~~text
.agents/skills/stream-clipper/
  SKILL.md
  agents/openai.yaml
  references/
  scripts/
  tests/
~~~

Os arquivos no diretório raiz (SKILL.md e scripts/) foram preservados como snapshot do projeto de origem para manter a rastreabilidade. Eles são legados e **não** são a skill ativa do Codex.

## Requisitos

- Windows 10/11, macOS ou Linux.
- Python 3.10+ (recomendado 3.11).
- FFmpeg e FFprobe disponíveis no PATH.
- Dependências listadas em .agents/skills/stream-clipper/requirements.txt.
- Espaço em disco para áudio, cache, previews e cortes finais.

A transcrição é local com Faster-Whisper. Modelos de fala não são baixados automaticamente por padrão: configure allow_model_download: true somente depois de revisar o modelo e o espaço necessário. Análise editorial é feita pelo Codex na conversa; não há API externa paga embutida.

## Instalar a skill pessoal no Windows

Abra o PowerShell na raiz do checkout:

~~~powershell
$skill = (Resolve-Path ".agents\skills\stream-clipper").Path
$destination = Join-Path $HOME ".agents\skills\stream-clipper"

py -3.11 "$skill\scripts\install.py" --source "$skill" --destination "$destination"

py -3.11 -m venv "$destination\.venv"
& "$destination\.venv\Scripts\python.exe" -m pip install --upgrade pip
& "$destination\.venv\Scripts\python.exe" -m pip install -r "$destination\requirements.txt"
~~~

Instale FFmpeg/FFprobe separadamente, se necessário:

~~~powershell
winget install --id Gyan.FFmpeg -e
~~~

Depois de instalar, feche e reabra o terminal. Faça o diagnóstico:

~~~powershell
$py = "$destination\.venv\Scripts\python.exe"
$clip = "$destination\scripts\clip.py"
& $py $clip doctor
& $py $clip config
& $py "$destination\scripts\install.py" --verify --destination "$destination"
~~~

O script de sincronização copia e verifica os arquivos da skill, cria backup de uma instalação anterior e preserva .venv, .runtime e runtime.json. A instalação de dependências é uma etapa separada e explícita.

## Instalação no macOS/Linux

A partir da raiz do checkout:

~~~bash
SKILL="$PWD/.agents/skills/stream-clipper"
DEST="$HOME/.agents/skills/stream-clipper"
python3 "$SKILL/scripts/install.py" --source "$SKILL" --destination "$DEST"
python3 -m venv "$DEST/.venv"
"$DEST/.venv/bin/python" -m pip install --upgrade pip
"$DEST/.venv/bin/python" -m pip install -r "$DEST/requirements.txt"
"$DEST/.venv/bin/python" "$DEST/scripts/clip.py" doctor
"$DEST/.venv/bin/python" "$DEST/scripts/install.py" --verify --destination "$DEST"
~~~

## Uso

1. Peça ao Codex para usar $stream-clipper com um link ou arquivo.
2. A skill executa apenas a inspeção de metadados primeiro.
3. Confira plataforma, canal, título, URL, duração e data. Autorize explicitamente aquela fonte.
4. Acompanhe a preparação por blocos. O Codex lê transcrição e sinais e importa cada bloco, inclusive os sem candidatos.
5. Revise os candidatos e previews. Aprovação dos candidatos é necessária antes da renderização final.

Comandos e exemplos estão em .agents/skills/stream-clipper/references/operations.md. Configurações estão em .agents/skills/stream-clipper/references/configuration.md.

## Benchmark CPU/GPU

O comando benchmark executa a mesma amostra de áudio no CPU (int8) e CUDA (float16), registra tempo de carregamento e transcrição, RAM do processo e uso total de VRAM observado. Use apenas uma fonte local ou VOD que você tenha inspecionado e autorizado.

Para a RTX 3060 12 GB, comece com o modelo tiny e uma amostra de 30–60 segundos. Depois, repita com base ou small se houver memória e espaço suficientes. O benchmark não presume CUDA operacional: consulte doctor e trate a execução CUDA como falha quando o runtime não estiver configurado. A contagem de dispositivos CUDA não substitui uma transcrição CUDA real.

O passo a passo, pré-requisitos e interpretação dos resultados estão em operations.md na pasta references.

## Manutenção, atualização e rollback

A fonte oficial da skill é .agents/skills/stream-clipper/ neste repositório. Não edite cópias instaladas manualmente. Consulte references/maintenance.md para sincronizar, verificar, atualizar com backup e fazer rollback.

## Testes e CI

Os testes ficam em .agents/skills/stream-clipper/tests/. O workflow .github/workflows/stream-clipper.yml instala FFmpeg, dependências e executa os testes em Ubuntu e Windows. Os testes audiovisuais geram mídia sintética local; não acessam lives de terceiros.

Executar localmente:

~~~powershell
Set-Location ".agents\skills\stream-clipper"
python -m compileall -q scripts
python -m unittest discover -s tests -v
~~~

## Origem e licença

- Upstream: https://github.com/davixavier-coder/skill-clips
- Fork: https://github.com/Dullestgoose360/skill-clips-codex
- Base auditada: 97b7b9084df7158b976fc8e0a0432e31fd919a74
- Branch de desenvolvimento: codex/general-clipper-adaptation

O commit de origem não contém LICENSE ou outro arquivo de concessão de licença. A visibilidade pública do GitHub não é, por si só, uma autorização para reutilizar ou redistribuir código. A auditoria e a atribuição estão em docs/ORIGIN-AUDIT.md. Não publique ou redistribua partes derivadas sem resolver essa questão jurídica com o titular dos direitos.

## Limitações conhecidas

- Não monitora lives ao vivo continuamente; aceita VODs finalizados.
- O chat replay é tentado somente para YouTube e pode não existir.
- A posição da facecam é amostrada; múltiplas faces, avatares e câmeras móveis podem exigir recorte manual.
- FFprobe/decodificação completa validam integridade técnica, mas não provam sincronização labial perceptual nem qualidade editorial.
- O reconhecimento da skill e a instalação na pasta pessoal precisam ser confirmados no Codex instalado no computador do usuário.
