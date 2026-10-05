# CLAUDE.md — Orchestration multi-agents de trading (Revolut X)

## Sources de vérité

- `docs/cahier-1-mecanique-deterministe.md` — mécanique déterministe (lot L0)
- `docs/cahier-2-orchestration.md` — orchestration, contrats, plan de lots

En cas de conflit entre ce fichier et les cahiers, les cahiers priment. Toute contradiction détectée est signalée à Quentin, jamais résolue seul.

## Statuts utilisés dans les cahiers

| Statut | Conduite |
| --- | --- |
| TRANCHÉ | Implémenter tel quel |
| DÉFAUT | Implémenter comme paramètre configurable, jamais en dur |
| PROPOSÉ | Implémenter ; un écart justifié donne lieu à une ADR |
| À TRANCHER | Ne jamais inventer de valeur : le démarrage échoue explicitement et la question remonte à Quentin |

## Règles de construction

1. Un seul lot par session (cahier 2, section 13). Ne jamais anticiper le lot suivant.
2. Toute API tierce (Revolut X en premier) est codée d'après sa documentation officielle actuelle, jamais de mémoire. Citer la page lue dans l'ADR.
3. STOP explicite de Quentin avant : tout ordre réel, tout déploiement, toute modification d'un invariant (I1–I9, S1–S10).
4. Chaque lot se termine par : tests verts en CI, une ADR par choix non couvert par les cahiers (`docs/adr/`), mise à jour de ce fichier, liste des questions remontées à Quentin.
5. Ne jamais redéployer pendant qu'une position est ouverte.

## Exigences techniques (cahier 1)

- Python ; `Decimal` pour tout montant, prix et quantité, jamais `float`
- `mypy --strict` en CI
- Aucune dépendance LLM ni LangGraph dans le conteneur garde-fou
- Clé Revolut X : droits trading seuls, injectée par secret Docker, jamais dans le code, l'image ou les logs

## Lot en cours : L0

Périmètre : cahier 1 complet (modules 1 à 6, tests niveaux 1 à 3).

Première tâche obligatoire : lire la documentation officielle Revolut X et produire `docs/adr/0001-revolut-x-api.md` couvrant : ordre stop natif, taille minimale d'ordre et pas de quantité, droits de la clé, limites de débit, restriction par IP. Tout écart avec le cahier 1 est remonté à Quentin avant de coder.

Ajouts au cahier 1 pour le scénario Grok Bot (PROPOSÉ, à inclure dans L0) :

- API HTTP exposée avec authentification par jeton (derrière Cloudflare Tunnel + Access)
- Notifications d'événements par mail, liste dans l'ADR 0002 (`METHOD_CHANGE_REQUIRED`, `HARD_STOP`, `SAFETY_NET_FIRED`, `BROKER_UNREACHABLE`, `LEDGER_ANOMALY`, `METHOD_VALIDATED`)
- Stop natif : `refuse_naked` (ADR 0002). Pas d'ouverture réelle sans stop posable
- Écarts 2 à 6 : ADR 0003. Limites BTC/EUR mesurées, droits `manual_ui`, frais sans défaut, position = aller-retour ouvert, IP limitée à la sortie du garde-fou au déploiement
- Mode « à blanc » : validation complète des ordres sans envoi au courtier, activé par défaut

STOP de fin de lot : non donné. ADR 0003 : pas d'ordre réel tant que le stop ne se pose pas.

## Agent skills

### Issue tracker

Issues et specs : GitHub Issues, via le shim `claude-gh-harness` (App `qveys-claude-bot`), jamais un `gh` nu. See `docs/agents/issue-tracker.md`.

### Triage labels

Cinq rôles par défaut, le nom du rôle est le label. See `docs/agents/triage-labels.md`.

### Domain docs

single-context (`GLOSSARY.md` et `docs/adr/` à la racine). See `docs/agents/domain.md`.
