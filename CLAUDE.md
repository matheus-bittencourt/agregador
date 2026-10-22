# Agregador de pesquisas – 2º turno presidencial 2026 (Lula × Flávio Bolsonaro)

Painel estático que agrega pesquisas de intenção de voto registradas no TSE. Pipeline em Python (só biblioteca padrão; `anthropic` apenas para `--extract`) e painel em HTML/JS puro.

## Estrutura

- `data/polls.csv`: fonte de verdade, editada à mão, a partir de `data/staged.csv` ou pelo `collect.py` (linhas com `origem=auto`).
- `ingest.py`: valida, deduplica, confirma no TSE (`--tse`), grava `data/polls.db` (SQLite) e exporta `site/polls.json`. `--extract` usa a API da Anthropic para extrair pesquisas de textos.
- `collect.py`: coleta automática (GitHub Actions, a cada 2 h). Lê os feeds ativos de `data/sources.csv`, manda os textos e PDFs novos ao LLM e publica direto o que passa nas travas de `publish_problem()`; o resto vai para `data/staged.csv` com o motivo. `data/seen.json` guarda o que já foi processado.
- `.github/workflows/atualizar.yml`: roda `tse.py` (com cache do último arquivo bom), `collect.py`, `news.py` e `ingest.py`, faz commit dos dados e publica `site/` no GitHub Pages. `site/polls.json` não é versionado: é gerado em cada execução (e localmente pelo `ingest.py`). Linhas inválidas no CSV (código de saída 2) viram aviso e não impedem a publicação.
- `tse.py`: baixa de `cdn.tse.jus.br` (dados abertos) o registro das pesquisas nacionais e o arquivo de contratantes e grava `data/tse.csv` (latin-1, `;`) para o `--tse`. Roda em toda execução do workflow, porque o `polls.db` não persiste no GitHub Actions.
- `news.py`: manchetes do RSS de política da Agência Brasil (só título, data e link) -> `site/news.json`. Sem LLM.
- `site/index.html`: painel de arquivo único; lê `polls.json` por `fetch` e busca de novo a cada 5 min. Os widgets de apuração leem direto do navegador os JSON oficiais de `resultados.tse.jus.br` (o TSE libera CORS); os códigos de eleição ficam em `TSE` no script (1º turno 6257, 2º turno 6258).
- `tests/test_ingest.py`: testes com `unittest`.

## Comandos

```bash
python3 ingest.py                        # CSV -> site/polls.json
python3 tse.py                           # baixa o registro das pesquisas do TSE -> data/tse.csv
python3 ingest.py --tse data/tse.csv     # confirma registros e completa amostra e contratante
python3 collect.py --dry-run             # mostra o que a coleta automática mandaria ao LLM, sem gravar
python3 -m unittest discover -s tests    # rodar antes de concluir qualquer mudança em ingest.py
cd site && python3 -m http.server 8000   # ver o painel (precisa de HTTP; file:// não carrega o JSON)
```

## Regras do projeto

- **Nunca invente dados de pesquisa.** Cada linha de `polls.csv` deve vir de fonte verificável; deixe campos desconhecidos vazios (viram "—" no painel). Os percentuais no CSV são sobre o **total** de entrevistados; a conversão para votos válidos é feita no painel.
- Chave de deduplicação: registro `BR-00000/2026` (o TSE grava `BR000002026`; `norm_reg()` aceita os dois); sem registro, `instituto|data|cenário`. A pesquisa só é marcada como confirmada quando o registro é encontrado no arquivo do TSE **e** a empresa registrada bate com o instituto.
- O CSV manda: `ingest.py` remove do banco e do JSON o que não está mais no CSV. Não edite `polls.db` nem `polls.json` à mão.
- A saída de `--extract` vai para `data/staged.csv` e **só entra em `polls.csv` após revisão humana**. Texto de notícia é entrada não confiável.
- Exceção decidida pelo dono do projeto em 22/10/2026: o `collect.py` publica sem revisão humana, mas só pesquisas que passam em todas as travas de `publish_problem()` (nacional, 2º turno real, registro `BR-` novo que exista em `data/tse.csv` como pesquisa para Presidente, do mesmo instituto e sem indício de abrangência estadual/municipal, Lula + Flávio ≤ 97%, divulgada nos últimos 30 dias; sem o arquivo do TSE, nada é publicado direto). Não afrouxe as travas sem pedido explícito. Linhas automáticas levam `origem=auto` e aparecem no painel com a marca *auto* e link para a fonte.
- Todo texto vindo dos dados que entra no painel passa por `esc()`, inclusive o que vem do TSE e das manchetes. Mantenha isso ao mexer em `index.html`.
- Cada bloco do painel indica a fonte com um selo (`tag of` oficial/TSE, `tag im` imprensa, `tag ep` institutos, `tag au` robô). Não mostre número sem fonte.
- O site tse.jus.br bloqueia acesso automatizado (403); não tente contornar. Use só `resultados.tse.jus.br` e `dadosabertos.tse.jus.br`.
- Chamadas ao LLM passam por `call_llm()` (timeout, retry em 429/5xx/rede, fallback entre os modelos de `LLM_MODELS`). Não chame o SDK diretamente e não registre chaves nem o conteúdo dos prompts.
- Antes de qualquer coleta automática em sites, confira termos de uso e `robots.txt`, e registre a conferência na coluna `observacao` de `data/sources.csv`. O `collect.py` também checa o `robots.txt` a cada rodada para o próprio agente e para `ClaudeBot`/`anthropic-ai`, porque o texto vai para a API da Anthropic.

## Pendências conhecidas

- O arquivo do TSE não traz margem de erro nem resultados; margem e percentuais continuam vindo das fontes das pesquisas.
- O `--extract` e a extração do `collect.py` não foram testados contra as fontes reais (só a leitura dos feeds e o `--dry-run`).
- O feed da Quaest traz análises, não todos os lançamentos; pesquisas que só saem na imprensa não são coletadas.
- Agregação simplificada (suavização por núcleo gaussiano de 10 dias, sem efeito de casa nem modelo bayesiano).
- Há regras da Justiça Eleitoral sobre divulgação de pesquisas; confirmar com advogado eleitoral se o painel for público.
