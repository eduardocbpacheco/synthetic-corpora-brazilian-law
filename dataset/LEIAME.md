# Depósitos

*[English version: `README.md`](README.md)*

Quatro depósitos, quatro DOI. Separados por licença e por ciclo de vida, não por arrumação:
num depósito só, a licença mais restritiva contaminaria tudo e cada correção de código
exigiria versionar 3 GB de dados.

| depósito | o que é | arquivos | tamanho |
|---|---|---:|---:|
| `corpus-treino` | o par bruto/expandido + os seis blocos de ajuste fino | 20 | 0,93 GB |
| `avaliacao-ablacao` | julgamentos das 180 condições + as respostas geradas | 542 | 1,29 GB |
| `benchmark-juizes` | vereditos de 31 juízes + padrão-ouro dos três juristas | 47.869 | 0,19 GB |
| `codigo` | instantâneo do pipeline no momento da submissão | 153 | 1,5 MB |

`DATASHEET.md` descreve o `corpus-treino` no formato de ficha de conjunto, com os defeitos
conhecidos e o custo medido de cada um.

## Congelar e conferir

```bash
juridico-env/bin/python dataset/congela.py                 # todos
juridico-env/bin/python dataset/congela.py corpus-treino   # um só
juridico-env/bin/python dataset/congela.py --conferir      # revalida contra o manifesto
```

O manifesto de cada depósito fica em `manifestos/<nome>.json`, com caminho, tamanho,
contagem de linhas e SHA-256 por arquivo. É ele que transforma "os dados estão no
repositório" em "estes bytes exatos produziram estes resultados".

## Por que as gerações vão junto dos julgamentos

O depósito de avaliação traz duas coisas: o veredito do juiz para cada critério e **o texto
que o modelo escreveu**. Sem o segundo, quem baixar herda a nossa escolha de corretor sem
poder contestá-la. Com ele, dá para rejulgar tudo com outro juiz — que é exatamente o que o
artigo do benchmark argumenta que deveria ser possível.

As duas coleções são pareadas por condição e conferidas: 271 julgamentos, 271 gerações,
nenhum órfão dos dois lados. Ficaram de fora os julgamentos em
`avaliacao/resultados/_prompt_antigo/`, de um prompt superado — eles documentam a mudança e
publicá-los junto dos correntes daria ao leitor dois conjuntos incompatíveis sem etiqueta.

## Antes de depositar

- [ ] Rodar `--conferir` e anexar a saída
- [x] Confirmar que os exames 39, 40 e 41 não aparecem no `corpus-treino` — `dataset/confere_vazamento.py`, verificado em 13/09
- [ ] Reservar DOI no Zenodo e pôr o identificador nos dois artigos
- [ ] Verificar os termos do serviço do modelo-professor quanto à redistribuição das camadas
