# Commands

On Windows, define $clip as the absolute scripts/clip.py path and $py as the installed skill's .venv/Scripts/python.exe. On Unix use .venv/bin/python. All commands accept global --home PATH before the subcommand. The default data directory is the current OS user's home plus stream-clipper, not the current working directory.

~~~powershell
& $py $clip doctor
& $py $clip config
& $py $clip discover --config C:\work\editorial.json
& $py $clip inspect 'https://www.youtube.com/watch?v=VIDEO_ID'
# Show the returned metadata and ask for explicit authorization for this exact source.
& $py $clip authorize SOURCE_ID --confirmation 'Exact user confirmation'
& $py $clip prepare SOURCE_ID --config C:\work\editorial.json
& $py $clip status
# Read each transcript block and create one strict JSON candidate array per block.
& $py $clip import-analysis SOURCE_ID --block 0 --file C:\work\block-0.json
& $py $clip review SOURCE_ID
& $py $clip preview SOURCE_ID --ids CANDIDATE_ID
# Present the candidates and preview; wait for the user's exact selection.
& $py $clip approve SOURCE_ID --ids CANDIDATE_ID --confirmation 'Exact user selection'
& $py $clip render SOURCE_ID --ids CANDIDATE_ID
~~~

Previews require source authorization but do not require final candidate approval. Final renders always require explicit candidate approval. Any edit changes the candidate identity and invalidates prior approval. There is no publish command.

## Benchmark CPU e GPU

O benchmark compara o mesmo trecho de áudio em processos separados, sem permitir fallback de CUDA para CPU. Isso evita registrar uma execução de CPU como se fosse GPU.

### Preparação segura

1. Execute doctor e guarde o resultado. Confirme a versão do Python, FFmpeg/FFprobe, Faster-Whisper, CTranslate2 e cuda_devices.
2. Inspecione uma fonte de vídeo que você possui ou está autorizado a analisar. O benchmark também exige autorização explícita dessa fonte.
3. Comece com um vídeo local curto (ou um VOD público permitido) e modelo tiny.
4. Modelos não são baixados por padrão. Se o modelo escolhido ainda não estiver no cache, revise espaço e tamanho e configure allow_model_download: true em um arquivo JSON fora da skill. O primeiro uso pode baixar o modelo uma vez.
5. Não rode outros trabalhos pesados durante a medição. Feche jogos e aplicações que ocupem a GPU. Registre se havia outros processos NVIDIA em execução.

Exemplo de configuração inicial (arquivo C:\work\benchmark.json):

~~~json
{
  "model": "tiny",
  "language": "pt",
  "device": "auto",
  "cpu_threads": 8,
  "allow_model_download": true
}
~~~

Depois de inspecionar a fonte e confirmar seus metadados:

~~~powershell
& $py $clip inspect "C:\work\amostra-autorizada.mp4"
# Leia platform, creator, title, URL, duração e data.
& $py $clip authorize SOURCE_ID --confirmation 'Autorizo o benchmark desta fonte local.'
& $py $clip benchmark SOURCE_ID --config C:\work\benchmark.json --seconds 60 --repeats 3
~~~

O tempo de amostra é limitado a 1–120 segundos e as repetições a 1–5. Para uma primeira comparação, 30–60 segundos e 3 repetições são suficientes. Para avaliar outro tamanho, altere model para base ou small somente depois de confirmar espaço de armazenamento e memória disponível. O modelo é idêntico nos dois dispositivos em cada execução.

### O que é medido

- load_seconds: carregamento do modelo no processo worker.
- transcribe_seconds: somente a transcrição, depois do carregamento.
- wall_seconds: carregamento + transcrição.
- rss_bytes: pico de memória RAM residente do processo e seus filhos.
- vram_baseline_mib / vram_total_mib: memória total reportada pelo nvidia-smi, antes e no pico observado; não é VRAM exclusiva do worker.
- median_vram_delta_mib: diferença mediana entre os valores totais observados.
- cuda_speedup_vs_cpu: mediana do tempo de transcrição CPU dividida pela mediana CUDA; acima de 1 significa CUDA mais rápida nessa amostra.
- cpu_cuda_transcript_similarity: similaridade textual entre as transcrições da CPU e CUDA. É apenas um indicador de consistência entre dispositivos, não WER/CER nem avaliação humana de precisão.

O relatório JSON é salvo no diretório da fonte e inclui todos os resultados individuais, falhas e resumo. Uma falha CUDA é registrada como falha; o benchmark não a substitui por CPU. Se cuda_devices for zero ou nulo, ou CUDA falhar no worker, verifique driver NVIDIA e a instalação compatível de CUDA/cuDNN exigida pela versão do CTranslate2 antes de repetir. A descoberta de GPU pelo doctor não prova que a transcrição CUDA funciona.

Para a RTX 3060 12 GB, o teste inicial com tiny reduz o custo do primeiro diagnóstico. Não há resultado de desempenho pré-assumido: escolha CPU ou GPU com base nos números obtidos no seu computador.

## Retomar e recuperar

Após interrupção, repita prepare com a mesma configuração. Blocos concluídos são reutilizados quando o checksum do artefato e a chave de configuração coincidem. Inspecione events.jsonl e status antes de tentar novamente. Não apague checkpoints para forçar repetição.

Um lock antigo exige recover-lock; o comando recusa recuperar quando o PID ainda existe. Confira manualmente identidade e horário do processo se houver possibilidade de reutilização do PID. Um coordenador encerrado à força pode deixar lock ou temporários, mas checkpoints concluídos continuam disponíveis.

Se o download por seção falhar, use plan-full; mostre estimativa de bytes, espaço livre e incerteza. Obtenha autorização específica para allow-full --confirmation TEXT. Tamanho desconhecido nunca é aprovado silenciosamente. Falta de espaço bloqueia o fallback mesmo com aprovação. Não tente contornar autenticação.

## Limpeza

cleanup-plan SOURCE_ID lista apenas diretórios temporários descartáveis. Mostre a lista ao usuário antes de executar:

~~~powershell
& $py $clip cleanup-plan SOURCE_ID
& $py $clip cleanup SOURCE_ID --confirmation 'DELETE LISTED TEMPORARIES'
~~~

O cache de fonte integral, transcrições, previews, aprovações e resultados finais são protegidos. Não exclua esses dados como parte de uma limpeza automática.
