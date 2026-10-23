# Промпт «маржа»: где я теряю деньги на товарах

К ролику с кодовым словом «маржа». Страница: https://ilyautov.github.io/gorilla-guides/marzha/

Нужен скилл `margin-analyzer` из [small-business-ru](https://github.com/ilyautov/small-business-ru):
`npx skills add ilyautov/small-business-ru` или в Claude Code
`/plugin marketplace add ilyautov/small-business-ru` и `/plugin install small-business-ru@small-business-ru`.
Шаблон выгрузки: https://ilyautov.github.io/gorilla-guides/marzha/shablon-vygruzki.csv

```
Вот выгрузка продаж моего магазина на маркетплейсе за сентябрь: vygruzka.csv.
Какая у меня маржа по товарам и где я теряю деньги?
Я на УСН «доходы» 6%, доход за прошлый год меньше 20 млн, НДС не плачу.
Считай со всеми расходами, которые есть в выгрузке.
Уточняющих вопросов не задавай, сразу анализ.
```
