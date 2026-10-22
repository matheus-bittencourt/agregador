# Agregador de pesquisas – 2º turno 2026

```
data/polls.csv   pesquisas curadas (fonte de verdade editável)
data/tse.csv     arquivo de registros do TSE (você baixa; ver abaixo)
ingest.py        valida, deduplica, confirma no TSE, grava SQLite e exporta JSON
site/index.html  painel (lê polls.json)
site/polls.json  gerado pelo ingest.py
```

## Rodar

```bash
python3 ingest.py                       # gera site/polls.json
python3 ingest.py --tse data/tse.csv    # também confirma registros no TSE
cd site && python3 -m http.server 8000  # abrir http://localhost:8000
```

O painel precisa ser servido por HTTP (abrir o arquivo direto não carrega o JSON).

## Fluxo de dados

1. **Registro do TSE.** Baixe o arquivo de pesquisas registradas no portal de dados abertos do TSE ou exporte do PesqEle e salve em `data/tse.csv`. O script cruza pelo número `BR-00000/2026`, marca a pesquisa como confirmada e completa amostra, margem e contratante. Os nomes das colunas em `TSE_COLS` são estimativas: confira o cabeçalho real e ajuste. Esse arquivo costuma trazer os dados do registro, não os percentuais, então os resultados vêm do passo seguinte.
2. **Resultados.** Adicione linhas em `data/polls.csv`, preferencialmente a partir do site do instituto. Para acelerar, `python3 ingest.py --extract artigos/*.txt` usa a API da Anthropic (`pip install anthropic`, variável `ANTHROPIC_API_KEY`) para extrair pesquisas de textos salvos e grava em `data/staged.csv`. **Revise sempre a mão** antes de copiar para `polls.csv`; o script nunca publica o que o modelo extraiu sozinho.
3. **Normalização.** O CSV guarda os percentuais sobre o total de entrevistados. A conversão para votos válidos é feita no painel.

## Confiabilidade das chamadas ao LLM

`--extract` usa timeout de 60 s, repete só erros retentáveis (429, 500, 502, 503, 504, 529 e falhas de rede) com backoff exponencial e jitter, respeita `retry-after` e, esgotadas as tentativas, passa ao próximo modelo da lista. Erros 400, 401 e 403 não são repetidos. Defina a ordem dos modelos permitidos em `LLM_MODELS`, por exemplo `LLM_MODELS=claude-sonnet-5-5,claude-haiku-5-5`; sem a variável, só o primeiro é usado. Cada chamada registra no stderr qual modelo respondeu, sem chaves nem texto dos prompts.

Cada item extraído passa pela mesma validação do CSV curado antes de ir para `data/staged.csv`.

## Testes

```bash
python3 -m unittest discover -s tests
```

Cobrem retries, fallback, timeout, erros não retentáveis, `retry-after`, validação e a sincronização do banco com o CSV.

## Papel do SQLite

O CSV é a fonte de verdade: o banco só guarda o que foi confirmado e completado pelo registro do TSE entre execuções, e linhas apagadas ou corrigidas no CSV saem do banco e do JSON. Para guardar histórico de versões, use controle de versão no `polls.csv`.

## Atualização periódica

Cron, a cada 30 minutos:

```
*/30 * * * * cd /srv/agregador && python3 ingest.py --tse data/tse.csv && cp site/polls.json /var/www/agregador/
```

Em GitHub Actions, use um workflow com `schedule: cron` que rode `ingest.py`, faça commit de `site/polls.json` e publique `site/` no GitHub Pages.

## Limitações

- Os dois passos de coleta (download do TSE e extração dos textos) dependem de rede e não foram testados contra as fontes reais; o ambiente em que escrevi o código não tinha acesso à internet. Foram testados: validação, deduplicação, SQLite, exportação e o cruzamento com um CSV simulado do TSE.
- Antes de coletar automaticamente de sites de institutos e portais, confira termos de uso e `robots.txt`.
- A agregação continua simplificada (média com núcleo gaussiano, sem efeito de casa).
- Há regras da Justiça Eleitoral sobre divulgação de pesquisas; se o painel for público, confirme com um advogado eleitoral.
