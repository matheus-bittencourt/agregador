# Agregador de pesquisas – 2º turno 2026

```
data/polls.csv   pesquisas curadas (fonte de verdade editável)
data/tse.csv     arquivo de registros do TSE (você baixa; ver abaixo)
ingest.py        valida, deduplica, confirma no TSE, grava SQLite e exporta JSON
collect.py       coleta automática a cada 2 h (fontes em data/sources.csv)
news.py          manchetes da Agência Brasil -> site/news.json
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

Cobrem retries, fallback, timeout, erros não retentáveis, `retry-after`, validação, a sincronização do banco com o CSV e, na coleta automática, `robots.txt`, leitura de feeds, travas de publicação e a marcação `origem=auto`.

## Papel do SQLite

O CSV é a fonte de verdade: o banco só guarda o que foi confirmado e completado pelo registro do TSE entre execuções, e linhas apagadas ou corrigidas no CSV saem do banco e do JSON. Para guardar histórico de versões, use controle de versão no `polls.csv`.

## Atualização automática (a cada 2 h)

`.github/workflows/atualizar.yml` roda a cada 2 horas no GitHub Actions:

1. `collect.py` lê os feeds marcados com `ativo=sim` em `data/sources.csv`, ignora o que já está em `data/seen.json`, busca a página e os PDFs do instituto quando o feed só traz resumo e manda o texto à API da Anthropic (via `call_llm()`).
2. Cada pesquisa extraída passa pela validação do CSV e pelas travas de publicação: precisa ser nacional, do 2º turno real, ter registro `BR-00000/2026` que ainda não esteja no CSV, Lula + Flávio ≤ 97% (acima disso costuma ser voto válido lido como total) e data dos últimos 30 dias. As que passam entram em `data/polls.csv` com `origem=auto`; as outras vão para `data/staged.csv` com o motivo.
3. `ingest.py` regenera `site/polls.json`, o workflow faz commit dos dados e publica `site/` no GitHub Pages. Um push no `main` também republica, sem coletar.

O painel busca `polls.json` de novo a cada 5 minutos. Pesquisas automáticas aparecem com a marca *auto*, que leva à fonte.

Para ativar: envie o repositório ao GitHub, crie o segredo `ANTHROPIC_API_KEY` em *Settings → Secrets and variables → Actions* e, em *Settings → Pages*, escolha a origem "GitHub Actions". Para testar a coleta sem gastar API: `python3 collect.py --dry-run`.

As fontes e a conferência de `robots.txt` e termos de uso ficam em `data/sources.csv`. O `collect.py` ainda checa o `robots.txt` a cada rodada, inclusive as regras para `ClaudeBot` e `anthropic-ai`.

## Apuração e manchetes

O painel mostra três quadros de apuração com dados oficiais do TSE: 2º turno no Brasil, 2º turno por UF (o visitante escolhe o estado) e o resultado do 1º turno. Eles leem direto do navegador os arquivos públicos de `resultados.tse.jus.br` (o mesmo que alimenta o app Resultados), sem passar pelo GitHub Actions. O 2º turno é consultado a cada 10 minutos antes do fim da votação e a cada minuto a partir das 16h30 de 25/10, só com a aba visível, e para quando o TSE encerra a totalização. Se o TSE não responder, o quadro mantém a última leitura e avisa.

Os códigos das eleições (`6257` e `6258`) ficam no objeto `TSE` do script; para outro pleito, confira em `resultados.tse.jus.br/oficial/comum/config/ele-c.json`.

O quadro de manchetes vem do RSS de política da Agência Brasil, filtrado por termos da eleição. Só título, data e link são mostrados, porque a EBC reserva os direitos do texto. O site do TSE bloqueia leitura automatizada, então as notícias do próprio TSE não entram.

## Limitações

- Os dois passos de coleta (download do TSE e extração dos textos) dependem de rede e não foram testados contra as fontes reais; o ambiente em que escrevi o código não tinha acesso à internet. Foram testados: validação, deduplicação, SQLite, exportação e o cruzamento com um CSV simulado do TSE.
- Antes de coletar automaticamente de sites de institutos e portais, confira termos de uso e `robots.txt`.
- A agregação continua simplificada (média com núcleo gaussiano, sem efeito de casa).
- Há regras da Justiça Eleitoral sobre divulgação de pesquisas; se o painel for público, confirme com um advogado eleitoral.
