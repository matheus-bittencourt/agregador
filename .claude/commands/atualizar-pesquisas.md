---
description: Adiciona pesquisas novas ao polls.csv, regenera o JSON e roda os testes
argument-hint: "[instituto ou período, opcional]"
---

Atualize as pesquisas do 2º turno presidencial (Lula × Flávio Bolsonaro). Foco: $ARGUMENTS

1. Leia `data/polls.csv` para ver o que já existe.
2. Busque na web pesquisas nacionais registradas no TSE que ainda não estão no CSV. Prefira o site do instituto e o número de registro `BR-00000/2026`.
3. Para cada pesquisa nova, adicione uma linha ao CSV com percentuais sobre o **total** de entrevistados (não votos válidos). Se só houver votos válidos, não adicione. Deixe vazio o que não encontrar; nunca estime.
4. Rode `python3 ingest.py` (e `--tse data/tse.csv` se o arquivo existir) e `python3 -m unittest discover -s tests`.
5. Resuma em poucas linhas: pesquisas adicionadas (instituto, data, registro, fonte), avisos do script e qualquer dado que ficou incerto.
