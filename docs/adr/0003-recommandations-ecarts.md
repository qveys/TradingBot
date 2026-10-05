# ADR 0003 — Recommandations sur les écarts 2 à 6

- Date : 2026-10-04
- Statut : décidé. Quentin a demandé d'appliquer la recommandation.
- Sources : cahier 1 §4, §6, §9, §10 ; ADR 0001 ; ADR 0002.
- Lecture du jour : `GET https://revx.revolut.com/api/1.0/public/configuration/pairs` (clé `BTC/EUR`). Même ressource que l'ADR 0001, section « Taille minimale d'ordre ».

Aucun ordre n'est envoyé. Aucun corps d'API n'est inventé.

## 2. Taille et pas BTC-EUR

Mesure du 2026-10-04, paire active. Ce ne sont pas les exemples du schéma.

| Champ | Valeur |
| --- | --- |
| `min_order_size` | 0.00000001 BTC |
| `min_order_size_quote` | 0.1 EUR |
| `base_step` | 0.00000001 |
| `quote_step` | 0.01 |
| `max_order_size` | 200 BTC |
| `max_order_size_quote` | 1000000 EUR |

`slippage` vaut 5 dans la réponse. L'unité n'est pas documentée sur cet objet : elle n'est pas utilisée.

`limits_for("BTC/EUR")` et `limits_for("BTC-EUR")` renvoient ces nombres. `decide()` ne les injecte pas : l'appelant les passe à `RulesConfig`. Avant un ordre réel, relire l'endpoint.

La clé publique est `BTC/EUR`. Les exemples de `placeOrder` utilisent un tiret (`BTC-USD`). Cette mesure ne choisit pas la forme à envoyer.

## 3. Droits de la clé

`KEY_RIGHTS_CHECK = "manual_ui"`. L'API ne relit pas les droits (ADR 0001). La vérification est l'enregistrement, par Quentin, qu'il a créé la clé dans l'UI Revolut X avec l'accès trading, pas la lecture seule. `key_rights_record` vide refuse toujours `start_real`. La constante n'est pas une preuve.

## 4. Frais taker

La configuration publique n'a pas de taux. Le 0,09 % taker du cahier §10 reste la mesure de Quentin, à reconfirmer avant le premier ordre. Il n'est pas le défaut du code. `fee_rate` absent produit `FEE_UNAVAILABLE` : un taux trop bas sous-estime le plafond R5.

## 5. Positions

Un solde n'est pas une position du filet. `GET /1.0/balances` sert au capital et au disponible (I4). La position du §6 est un aller-retour encore ouvert au registre. Aplatir tout solde BTC vendrait des avoirs hors bot. Le filet reste non codé (ADR 0002).

## 6. Liste blanche d'IP

Avant toute clé réelle, la liste blanche de la clé ne contient que l'IP de sortie du conteneur garde-fou. L'API ne dit pas si une liste vide autorise tout. Aucun contrôle au démarrage : il n'y a pas d'endpoint pour le lire.

## Ordre réel

Quentin ne tranche pas le STOP du premier ordre. La recommandation s'applique : il n'est pas donné. Le mode à blanc reste le défaut. `refuse_naked` interdit l'envoi. Le niveau 3 du cahier (ordre BTC-EUR réel, stop natif posé) attend une écriture de stop documentée.

## Déjà décidé

Mails et `STOP_POLICY = "refuse_naked"` : ADR 0002. Intervalle du filet : 5 s (cahier, Q11), compatible avec 100 lectures authentifiées par seconde. Il n'est pas codé tant que le stop ne se pose pas.
