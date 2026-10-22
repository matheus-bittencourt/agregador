# Agregador de pesquisas – 2º turno presidencial 2026 (Lula × Flávio Bolsonaro)

Painel estático que agrega pesquisas de intenção de voto registradas no TSE. Pipeline em Python (só biblioteca padrão; `anthropic` apenas para `--extract`) e painel em HTML/JS puro.

## Estrutura

- `data/polls.csv`: fonte de verdade, editada à mão ou a partir de `data/staged.csv`.
- `ingest.py`: valida, deduplica, confirma no TSE (`--tse`), grava `data/polls.db` (SQLite) e exporta `site/polls.json`. `--extract` usa a API da Anthropic para extrair pesquisas de textos.
- `site/index.html`: painel de arquivo único; lê `polls.json` por `fetch`.
- `tests/test_ingest.py`: testes com `unittest`.

## Comandos

```bash
python3 ingest.py                        # CSV -> site/polls.json
python3 ingest.py --tse data/tse.csv     # confirma registros e completa amostra, margem, contratante
python3 -m unittest discover -s tests    # rodar antes de concluir qualquer mudança em ingest.py
cd site && python3 -m http.server 8000   # ver o painel (precisa de HTTP; file:// não carrega o JSON)
```

## Regras do projeto

- **Nunca invente dados de pesquisa.** Cada linha de `polls.csv` deve vir de fonte verificável; deixe campos desconhecidos vazios (viram "—" no painel). Os percentuais no CSV são sobre o **total** de entrevistados; a conversão para votos válidos é feita no painel.
- Chave de deduplicação: registro `BR-00000/2026`; sem registro, `instituto|data|cenário`. A pesquisa só é marcada como confirmada quando o registro é encontrado no arquivo do TSE.
- O CSV manda: `ingest.py` remove do banco e do JSON o que não está mais no CSV. Não edite `polls.db` nem `polls.json` à mão.
- A saída de `--extract` vai para `data/staged.csv` e **só entra em `polls.csv` após revisão humana**. Texto de notícia é entrada não confiável.
- Todo texto vindo dos dados que entra no painel passa por `esc()`. Mantenha isso ao mexer em `index.html`.
- Chamadas ao LLM passam por `call_llm()` (timeout, retry em 429/5xx/rede, fallback entre os modelos de `LLM_MODELS`). Não chame o SDK diretamente e não registre chaves nem o conteúdo dos prompts.
- Antes de qualquer coleta automática em sites, confira termos de uso e `robots.txt`.

## Pendências conhecidas

- `TSE_COLS` em `ingest.py` tem nomes de colunas estimados; conferir com o cabeçalho real do arquivo de dados abertos do TSE.
- O download do arquivo do TSE e o `--extract` não foram testados contra as fontes reais.
- Agregação simplificada (suavização por núcleo gaussiano de 10 dias, sem efeito de casa nem modelo bayesiano).
- Há regras da Justiça Eleitoral sobre divulgação de pesquisas; confirmar com advogado eleitoral se o painel for público.
