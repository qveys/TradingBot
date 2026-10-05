# ADR 0001 — API Revolut X (lecture, rien tranché)

- Date de lecture : 2026-10-03
- Statut : constat. Aucun écart ci-dessous n'est tranché. Pas de client courtier.
- Schéma : OpenAPI 3.1.0, `info.version` 1.0.0, serveur `https://revx.revolut.com/api`

## Pages ouvertes

Lues :

- https://developer.revolut.com/docs/revolut-x-crypto-exchange-apis
- https://developer.revolut.com/docs/api/revolut-x-crypto-exchange.yml (schéma lié par « View schema » ; lu en entier)
- https://developer.revolut.com/docs/api/revolut-x-crypto-exchange/operations/place-order.md
- https://developer.revolut.com/docs/api/revolut-x-crypto-exchange/operations/get-currency-pairs-public.md
- https://help.revolut.com/help/wealth/cryptocurrencies/crypto-exchange/api-trading/question-what-api-does-revolut-x-provide/

Non exploitables :

- https://www.revolut.com/legal/crypto-exchange-trading-rules — page de contrôle de sécurité, contenu des règles non obtenu. Aucun minimum d'ordre n'en est tiré.
- https://developer.revolut.com/docs/guides/manage-accounts/api-keys/revolut-x-api-keys — 404. Ce n'est pas une page Revolut X.

Les faits ci-dessous viennent de ces pages. Un sujet absent y est marqué inconnu.

## Ordre stop natif

`POST /1.0/orders` (`placeOrder`) ne place qu'un ordre dont `order_configuration` contient exactement un de `limit` ou `market`. Le corps publié n'a pas de champ stop, conditionnel, ni `tpsl`.

Le schéma décrit pourtant des ordres de type `market`, `limit`, `conditional`, `tpsl`, `twap` sur les lectures (`Order`, `OrderDetails`) :

- `conditional` : soumis une fois un `trigger_price` atteint.
- `tpsl` : « sets or adjusts the Take Profit and Stop Loss settings for a position ». `stop_loss` (et/ou `take_profit`) est un `OrderTrigger` : `trigger_price`, `type` `market` ou `limit`, `trigger_direction` `ge` ou `le`, `time_in_force` `gtc` ou `ioc`, `execution_instructions`, `limit_price` requis si `type` est `limit`.
- `on_fill` : stratégie de sortie Take Profit/Stop Loss liée, soumise une fois l'ordre courant exécuté. Présent sur le détail d'ordre, absent du corps de `placeOrder`.

`GET /1.0/orders/active` filtre `order_types` parmi `limit`, `conditional`, `tpsl`, `twap`. `DELETE /1.0/orders` et `DELETE /1.0/orders/{venue_order_id}` annulent aussi conditionnel, TPSL et TWAP.

Aucun chemin d'écriture du schéma ne crée un `tpsl`, un `conditional`, ou un `on_fill`. La pose d'un stop natif par cette API est donc inconnue.

## Taille minimale d'ordre

Pas de minimum unique dans les pages lues. Il est par paire.

`GET /1.0/public/configuration/pairs` (et `GET /1.0/configuration/pairs`, authentifié) renvoie, pour chaque paire : `min_order_size` (quantité minimale en devise de base), `min_order_size_quote` (quantité minimale en devise de cotation), `max_order_size` (maximum en base). Les nombres du schéma (`BTC/USD` : `min_order_size` `"0.0000001"` ; `ETH/EUR` : `"0.00001"`) sont des exemples du schéma, pas une mesure de BTC-EUR. Le minimum BTC-EUR réel n'est pas dans ces pages.

## Pas de quantité

Même objet paire : `base_step`, « the minimal step for changing the quantity in the base currency » ; `quote_step`, « the minimal step for changing the amount in the quote currency ». Exemples du schéma, les deux paires : `base_step` `"0.0000001"`, `quote_step` `"0.01"`. Pas un pas constaté pour BTC-EUR.

`GET /1.0/public/configuration/currencies` expose `scale` (nombre de décimales de la devise). Ce n'est pas documenté comme le pas d'ordre. Un pas de prix distinct de `quote_step` n'est pas documenté : inconnu.

Les exemples mélangent `BTC/USD` (clé de configuration) et `BTC-USD` (symbole de chemin et de `placeOrder`). La forme à utiliser pour BTC-EUR n'est pas fixée par ces pages.

## Droits de la clé

Page d'aide : chaque clé a un jeu de droits. On peut donner un accès lecture seule ou un accès trading complet, et autoriser l'usage via Revolut X MCP et CLI. Réglage dans le profil de l'app web Revolut X (https://exchange.revolut.com/home?open=api-keys).

Le portail développeur : clé de 64 caractères alphanumériques, en-tête `X-Revx-API-Key`, plus `X-Revx-Timestamp` et `X-Revx-Signature` (Ed25519). Chaque clé correspond au compte (Business ou Retail). Le schéma ne décrit pas de scope, et aucun endpoint ne relit les droits d'une clé.

Un droit « retrait » ou « sans retrait » n'est pas nommé. Inconnu : si « trading complet » exclut le retrait, et comment le vérifier par l'API.

## Limites de débit

Pas de plafond global. Chaque opération a son seau de jetons. `429` : en-tête `Retry-After`, délai en millisecondes.

| Opération | Limite |
| --- | --- |
| Publics (`/2.0/public/order-book/{symbol}`, `/1.0/public/tickers`, `/1.0/public/candles/{symbol}`, `/1.0/public/trades/all`, `/1.0/public/configuration/currencies`, `/1.0/public/configuration/pairs`, et les dépréciés `/1.0/public/last-trades`, `/1.0/public/order-book/{symbol}`) | 1 jeton / seconde, 1 jeton / requête |
| `POST /1.0/orders` | 10 / seconde et 1 000 / jour, 1 jeton / requête |
| `PUT /1.0/orders/{venue_order_id}` | 10 / seconde, 1 jeton / requête. Pas de limite journalière dans la table. |
| `GET /1.0/orders/historical`, `GET /1.0/trades/private/{symbol}`, `GET /1.0/transactions`, `GET /1.0/trades/all/{symbol}` | 100 / seconde et 1 000 / minute, 1 jeton / jour de la plage demandée |
| `GET /1.0/candles/{symbol}` (authentifié) | 500 000 / seconde et 5 000 000 / minute, coût `max(5 000, nombre de bougies)` jetons |
| Autres authentifiés lus (`balances`, ordres actifs, ordre par id, annulations, fills, carnet, tickers, transaction par id, configurations) | 100 / seconde et 1 000 / minute, 1 jeton / requête |

## Restriction par IP

Page d'aide : on peut modifier la liste blanche d'IP d'une clé (menu de la clé, « Edit »). L'exemple de réponse `401` du schéma a pour message « API key can only be used for authentication from whitelisted IP ».

Inconnu : liste obligatoire ou non, liste vide = toute IP ou aucune, nombre d'adresses, CIDR, et si ce message est la seule cause d'un 401.

## Écarts avec le cahier 1

Comparé à `docs/cahier-1-mecanique-deterministe.md`. Le constat ci-dessous ne change pas. Le point 1 et les mails sont décidés dans l'ADR 0002. Les points 2 à 6 sont décidés dans l'ADR 0003.

1. Stop natif. Le cahier (§4) envoie l'ordre puis pose tout de suite le stop natif ; le filet (§6) cherche ce stop actif. Le corps publié de `POST /1.0/orders` ne le porte pas. Les types `tpsl` / `conditional` se lisent et s'annulent ; leur création par l'API n'est pas documentée. ADR 0002 : pas de pose inventée, pas d'ouverture réelle sans stop.
2. Taille minimale et pas. Le cahier arrondit au pas et refuse sous le minimum Revolut X, et le niveau 3 vise un BTC-EUR à la taille minimale. Les pages donnent des champs par paire et des exemples qui ne sont pas BTC-EUR. La page légale n'a pas pu être lue. Aucun nombre ne doit être codé en dur.
3. Droits. Le cahier exige trading seul, aucun retrait, vérifié avant tout ordre réel ; la méthode de vérification est À TRANCHER selon l'API. L'API documente lecture seule ou trading complet, plus MCP/CLI. Elle ne nomme pas le retrait et n'expose pas de lecture des droits. La méthode reste vide.
4. Frais. Le cahier (PROPOSÉ) lit un taux taker à l'API. Le schéma donne `total_fee` et `fee_currency` sur un ordre, et un booléen maker sur un trade. Pas de taux taker. Inconnu.
5. Positions. Le filet lit « les positions détenues ». Le schéma a `GET /1.0/balances`, pas de ressource positions. Inconnu si un solde spot est la position.
6. IP. Le cahier ne fixe pas de liste blanche. L'aide et l'exemple 401 montrent qu'une liste peut exister, sans dire si elle est obligatoire pour le conteneur garde-fou.
7. Débit du filet. Le défaut cahier (5 s) n'est pas contredit par les seaux authentifiés de lecture (100 / seconde, 1 000 / minute). L'ADR 0002 n'autorise pas à coder le filet : aucune ouverture réelle ne part sans stop.
