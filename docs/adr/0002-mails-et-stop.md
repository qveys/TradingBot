# ADR 0002 — Mails et stop natif

- Date : 2026-10-04
- Statut : décidé. Quentin a demandé d'appliquer la recommandation.
- Sources : cahier 1 §4, §6 et §9 ; cahier 2 (événements) ; ADR 0001.

## Mails

Le §9 dit quels faits notifier. Les codes sont ceux déjà écrits dans les cahiers. `mail_events` n'est plus vide.

| Fait du §9 | Code |
| --- | --- |
| Seuil de survie franchi | `METHOD_CHANGE_REQUIRED` |
| Arrêt dur | `HARD_STOP` |
| Filet déclenché | `SAFETY_NET_FIRED` |
| Courtier injoignable | `BROKER_UNREACHABLE` |

`METHOD_CHANGE_REQUIRED` couvre aussi les autres changements forcés (drawdown, SPRT bas, Kelly nul, troncature) : le superviseur doit choisir la méthode suivante. `HARD_STOP` et `BROKER_UNREACHABLE` n'avaient pas de code. Ce sont les identifiants à émettre.

Deux événements hors tableau §9 partent aussi, parce que le canal sans dashboard est le mail :

| Code | Pourquoi |
| --- | --- |
| `LEDGER_ANOMALY` | divergence du registre, déjà émise au superviseur |
| `METHOD_VALIDATED` | le SPRT a validé la méthode |

## Stop

`POST /1.0/orders` ne pose que `limit` ou `market` (ADR 0001). Aucun corps `tpsl` n'est inventé.

Vendre au marché toute position ouverte, faute de stop constatable, la fermerait au tick suivant. Ce n'est pas le filet du §6. Le §6 vend au marché seulement si un stop a disparu sans être exécuté.

`STOP_POLICY = "refuse_naked"`. Aucune ouverture réelle n'est envoyée tant que l'API ne permet pas de poser le stop. Le mode à blanc et `on_accept` restent la couture de test. Le filet n'est pas codé ici.
