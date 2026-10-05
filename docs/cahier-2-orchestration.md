# Cahier des charges 2 — Orchestration multi-agents (construction par IA)

Oct 3, 2026 · @Quentin Veys

## 1. Objet, périmètre et règles de construction

Ce cahier spécifie tout ce qui reste à construire au-delà de la mécanique déterministe (cahier 1), pour qu'un harnais IA (Claude Code) puisse livrer le système complet lot par lot. Le but réel du projet est d'apprendre à construire une orchestration multi-agents à boucle de rétroaction ; le trading sur Revolut X en est le terrain d'application avec de l'argent réel (\~100 €).

Même convention que le cahier 1 : **TRANCHÉ** = décision de Quentin ; **PROPOSÉ** = choix de conception à valider ; **À TRANCHER** = donnée manquante.

| Cahier | Contenu | Prérequis |
| --- | --- | --- |
| 1 — Mécanique déterministe | Garde-fous, dimensionnement, filet, registre, SPRT, clé | Aucun |
| 2 — Ce document | Contrats, automate, graphe d'agents, backtest, prompts, routage, observabilité, méta, exploitation | Cahier 1 livré et vert |

Règles imposées à l'IA qui construit (PROPOSÉ) :

1. Un lot (section 13) par session ; ne jamais anticiper le lot suivant.
2. Ce document et le cahier 1 sont la source de vérité ; ils sont copiés dans le dépôt et référencés dans `CLAUDE.md`.
3. Un paramètre À TRANCHER n'est jamais remplacé par une valeur plausible : le code le laisse vide, le démarrage échoue explicitement, et la question remonte à Quentin.
4. Toute API tierce (Revolut X, LangGraph, LiteLLM, Langfuse, OpenRouter, Jev) est codée d'après sa documentation officielle courante, jamais de mémoire.
5. STOP explicite de Quentin avant tout ordre réel, tout déploiement et tout changement d'un invariant.
6. Chaque lot se termine par ses tests verts et une note de décisions (ADR) pour tout choix non couvert ici.

## 2. Vue d'ensemble

Sept composants forment une seule chaîne verticale, encadrée par deux couches transverses ; le garde-fou du cahier 1 est le seul passage vers le courtier (TRANCHÉ).

&#91;embedded content: vue d'ensemble · 7 composants, une chaîne verticale, 2 couches transverses\]

Le superviseur ne reçoit que ce que la chaîne n'a pas su résoudre ; la couche méta se nourrit des métriques et n'agit jamais sur elle-même.

## 3. Objectif global et invariants système

L'objectif global est écrit une fois par Quentin en langage humain ; l'orchestrateur l'interprète mais ne peut jamais le redéfinir (TRANCHÉ).

Contenu tranché : ne pas perdre le capital en priorité, le faire croître en second ; mix croissance rapide et long terme ; le capital représente la vie de l'agent. Formulation finale du texte : À TRANCHER, à écrire par Quentin, stockée en lecture seule et injectée dans le prompt de l'orchestrateur-conseiller et du planificateur.

| # | Invariant système | Statut |
| --- | --- | --- |
| S1 | Aucune validation humaine des ordres : le système est autonome sur la décision de trading | TRANCHÉ |
| S2 | Une seule chaîne verticale : un échelon ne remonte au suivant que s'il ne peut pas résoudre | TRANCHÉ |
| S3 | Cloisonnement : chaque couche ne voit que les sorties factuelles de la précédente, jamais ses détails bruts | TRANCHÉ |
| S4 | Toute transition d'état, de niveau de replan ou de méthode est mécanique ; un LLM ne choisit jamais le moment | TRANCHÉ |
| S5 | Toute action proposée par un LLM passe par les garde-fous du cahier 1 | TRANCHÉ |
| S6 | Le juge est toujours d'une famille de modèles différente du jugé | TRANCHÉ |
| S7 | La couche méta optimise les couches en dessous, jamais elle-même | TRANCHÉ |
| S8 | Schéma de données évolutif en additif uniquement | TRANCHÉ |
| S9 | Budget : abonnements grand public déjà payés + OpenRouter à l'usage, rien d'autre | TRANCHÉ |
| S10 | Pas de fine-tuning | TRANCHÉ |

## 4. Contrats de données entre couches

Les contrats sont le prérequis de tout prompt : chaque sortie de LLM est un objet validé par schéma (Pydantic, PROPOSÉ), rejeté et rejoué s'il ne valide pas. Les champs ci-dessous sont un minimum ; seuls les champs marqués TRANCHÉ viennent de décisions explicites.

| Contrat | Émetteur → récepteur | Champs minimaux | Statut |
| --- | --- | --- | --- |
| `MethodDeclaration` | Planificateur → contrôle mécanique | method\_id, description, fréquence, horizon, critère de sélection des paires, règle d'entrée, règle de sortie, règle de stop | fréquence/horizon/paires TRANCHÉ ; reste PROPOSÉ |
| `Plan` | Planificateur → exécutant | method\_id, étapes ordonnées, critère de fin de chaque étape | PROPOSÉ |
| `OrderIntent` | Exécutant → API interne (cahier 1) | method\_id, pair, side, stop\_price, annotation (signal, justification) | PROPOSÉ (cahier 1) |
| `ExecutionResult` | Registre → superviseur, méta | type d'ordre, quantité, prix, heure, solde après ordre, frais réels | TRANCHÉ |
| `StepFailure` | Exécutant → cycle de replan | étape, classe d'erreur (transitoire, logique récupérable, irrécupérable), message, compteurs | classes TRANCHÉ |
| `Escalation` | Cycle de replan → superviseur | chemin (technique ou pertes trading), historique des tentatives, référence de trace | 2 chemins TRANCHÉ |
| `SupervisorDecision` | Superviseur → orchestrateur ou planificateur | chemin technique : correction de la façon de travailler ; chemin trading : method\_id suivante | TRANCHÉ |
| `AdvisorProposal` | Conseiller LLM → automate | situation décrite, action proposée parmi une liste fermée, justification | PROPOSÉ (liste fermée) |
| `MetaChange` | Méta → registre de versions | cible (prompt, règle de routage, champ de schéma), version, diff, résultat shadow, décision | PROPOSÉ |
| Événements | Cahier 1 → superviseur, automate | `LEDGER_ANOMALY`, `SAFETY_NET_FIRED`, `METHOD_CHANGE_REQUIRED`, `METHOD_VALIDATED` | PROPOSÉ (cahier 1) |

Règles de version : chaque contrat porte un numéro de version ; la méta ne peut qu'ajouter un champ optionnel, et met à jour le prompt du consommateur dans le même changement (TRANCHÉ).

## 5. Automate orchestrateur

L'orchestrateur est un automate à états en code pur : toutes ses transitions sont déclenchées par des faits mesurés, et un LLM conseiller n'intervient que dans l'état « inconnu » (TRANCHÉ).

&#91;embedded content: automate orchestrateur · états et transitions mécaniques\]

Précisions :

- Seuil de survie franchi : changement de méthode forcé et notification, pas un arrêt global. Cette décision plus récente remplace la version antérieure « seuil de survie → tout arrêter » (TRANCHÉ).
- La méthode choisie par le superviseur repasse par compatibilité et backtest avant de trader (PROPOSÉ).
- État inconnu : exemples cités par Quentin, courtier en panne prolongée, planificateur en échec répété, événement de marché exceptionnel. Chaque appel au conseiller est journalisé pour que la méta convertisse les cas récurrents en règles (TRANCHÉ). Critères d'entrée chiffrés : À TRANCHER.
- Nombre maximal de rejets successifs avant passage en état inconnu : À TRANCHER.

## 6. Graphe d'agents (LangGraph) et cycle de replan

LangGraph porte la couche d'exécution planificateur → exécutant avec checkpointing ; les transitions du cycle de replan sont des arêtes conditionnelles en code, jamais une décision de LLM (TRANCHÉ).

Nœuds (PROPOSÉ) : `plan` (LLM planificateur), `execute_step` (LLM exécutant + outils), `classify_failure` (code), `retry`, `patch` (LLM planificateur, modifie l'étape fautive), `replan` (LLM planificateur, plan complet), `escalate` (sortie vers le superviseur).

| Classe d'erreur | Traitement | Statut |
| --- | --- | --- |
| Transitoire | Rejouer à l'identique | TRANCHÉ |
| Logique récupérable | Retry avec l'erreur en contexte, puis patch, puis replan | TRANCHÉ |
| Irrécupérable | Escalade directe, sans retry | TRANCHÉ |

Compteurs bornés obligatoires par niveau (retry, patch, replan) ; valeurs À TRANCHER. Règles de classification d'une erreur dans l'une des trois classes : À TRANCHER (PROPOSÉ : par type d'exception et code HTTP pour les erreurs d'outil, par échec de validation de schéma pour les sorties LLM).

Outils de l'exécutant (PROPOSÉ, liste fermée) : soumettre un `OrderIntent` à l'API interne, lire le marché (prix, carnet, chandelles) via le garde-fou en lecture seule, lancer le backtest. Aucun accès à la clé, au registre en écriture ni au réseau courtier (cahier 1, I2).

Checkpointing : persistant sur disque pour reprendre après crash (backend À TRANCHER).

## 7. Méthode : déclaration, compatibilité, backtest pré-filtre

Une méthode n'atteint le trading réel qu'après trois filtres successifs, tous déterministes sauf la proposition elle-même (TRANCHÉ) : proposition par le planificateur, contrôle mécanique de compatibilité, backtest pré-filtre.

| Filtre | Vérifie | Échec → | Statut |
| --- | --- | --- | --- |
| Contrôle de compatibilité | Fréquence et horizon tenables avec les frais et limites de l'API ; paires sélectionnables par le filtre spread < 0,2 % + volume ; règle de stop présente | Retour au planificateur avec le motif | TRANCHÉ ; critères chiffrés À TRANCHER |
| Backtest pré-filtre | Élimine les méthodes manifestement mauvaises avant de consommer des trades réels ; lancé par l'exécutant, code Python déterministe, pas juge final | Retour au planificateur | TRANCHÉ |
| Verrou de méthode | Une seule méthode active ; aucun changement avant 30 trades sauf seuil de survie | — | TRANCHÉ (cahier 1, M5) |

À trancher pour le backtest : source et profondeur des données historiques, modélisation des frais (taker 0,09 % + spread mesuré) et du glissement, critère de rejet chiffré, garde-fou contre le surajustement (piste citée par Quentin : cadre Bailey / López de Prado, deflated Sharpe ratio, minimum backtest length), nombre maximal de propositions rejetées avant escalade.

Exigence (PROPOSÉ) : la méthode déclarée est exécutable par du code (règles paramétrées), pas une consigne en langage libre réinterprétée à chaque trade ; sinon backtest et trading réel ne testent pas la même chose.

## 8. Prompts système

Cinq rôles LLM ont un prompt à rédiger ; l'IA constructrice les rédige à partir de cette spécification, après l'interview relentless prévue sur les angles morts (TRANCHÉ : interview avant rédaction).

| Rôle | Reçoit | Produit | Interdits | Juge / palier |
| --- | --- | --- | --- | --- |
| Planificateur | Objectif global, état du système, historique factuel des méthodes, motifs de rejet | `MethodDeclaration`, `Plan`, patch ou replan | Choisir le moment d'un changement ; fixer un paramètre de risque | Palier décidé par Jev |
| Exécutant | Étape du plan, données de marché via outils | `OrderIntent`, `StepFailure` | Fixer une quantité ; déclarer une confiance qui influence la mise ; voir la clé | Palier décidé par Jev |
| Superviseur — chemin technique | `Escalation` technique, erreurs récurrentes | `SupervisorDecision` (correction de méthode de travail) | Juger un modèle de sa propre famille | Famille ≠ exécutant |
| Superviseur — chemin trading | Résultats factuels de la méthode, motif mécanique du changement | `SupervisorDecision` (method\_id suivante) | Décider du moment ; garder la méthode sortante | Famille ≠ planificateur (PROPOSÉ) |
| Conseiller orchestrateur | Description de l'état « inconnu », objectif global | `AdvisorProposal` dans une liste fermée | Toute action hors liste ; contourner les garde-fous | Palier élevé (PROPOSÉ) |
| Critique + optimiseur méta | Traces d'échec, carnet d'erreurs, prompt actuel | Gradient textuel puis `MetaChange` | Modifier son propre prompt ; supprimer un champ de contrat | Famille ≠ jugé |

Gabarit commun de chaque prompt (PROPOSÉ) : rôle et place dans la chaîne ; objectif global (lecture seule) ; entrées ; schéma de sortie exact ; interdits ; conduite à tenir en cas d'incertitude (échouer avec `StepFailure`, jamais inventer). Chaque prompt est versionné, rejouable et instrumenté pour le shadow mode (section 11).

Résolu ici : le schéma de sortie de chaque rôle est fixé par la section 4 ; le texte du prompt n'invente aucun champ.

## 9. Routage multi-modèles

Chaque appel LLM individuel passe par le routeur : Jev (via OpenRouter) décide du palier, LiteLLM exécute l'appel vers le provider (TRANCHÉ). LLMRouter et le scorer séparé sont abandonnés.

| Brique | Rôle | Statut |
| --- | --- | --- |
| Jev (TypeSafe AI, via OpenRouter) | Choix typé du palier (cher, moyen, pas cher) avec probabilités ; la contrainte « famille différente du jugé » fait partie de la question posée | TRANCHÉ ; contrat d'appel à lire dans la doc officielle |
| LiteLLM (conteneur central) | Point d'entrée unique, API unifiée vers tous les providers | TRANCHÉ |
| Conteneur par abonnement | Claude Code, Codex, Grok : harnais natif + authentification OAuth de l'abonnement, exposé en API compatible OpenAI, vu par LiteLLM comme un provider | TRANCHÉ |
| OpenRouter | Accès multi-familles, seule dépense à l'usage autorisée | TRANCHÉ |

À trancher : table palier → modèles (point de départ : leaderboards publics orientés code, ajustés ensuite par l'observation) ; famille de chaque modèle ; comportement si le quota d'un abonnement est épuisé (repli, attente) ; politique en cas d'indisponibilité de Jev (palier par défaut fixe, PROPOSÉ).

Réutilisation : le même routeur sert à my-housekeeper, avec en plus une contrainte de quota par abonnement (TRANCHÉ) ; le construire comme un service indépendant du projet trading (PROPOSÉ).

Risque à vérifier avant construction : la conformité de l'usage des abonnements grand public via leur harnais natif dans un conteneur avec les conditions de chaque provider. Quentin a écarté toute simulation de terminal interactif ; le reste n'a pas été vérifié.

## 10. Observabilité

Deux sources distinctes : Langfuse trace les appels LLM, le registre des trades (cahier 1) porte les faits financiers. Le consommateur principal est la couche méta, pas un humain (TRANCHÉ).

| Source | Contenu | Statut |
| --- | --- | --- |
| Langfuse auto-hébergé | Chaque appel LLM : rôle, version de prompt, modèle, palier, latence, coût, validation de schéma | Langfuse penché, pas tranché ferme |
| Registre des trades | Résultats factuels de chaque trade | TRANCHÉ (cahier 1) |
| Journal de l'automate | Transitions d'état, appels au conseiller, déclencheurs | PROPOSÉ |

Métriques minimales pour la méta (PROPOSÉ, à compléter) : taux de sorties valides par rôle ; taux de retry, patch, replan, escalade ; taux de rejet des méthodes par filtre ; coût et latence par palier ; résultat factuel par méthode et position par rapport à l'objectif. L'observabilité remonte les faits bruts, sans décider ce qui compte comme échec (TRANCHÉ).

À trancher : Langfuse confirmé ou non ; son hébergement compatible avec la contrainte budget S9 (l'estimation discutée était \~150 $/mois d'infra, à recouper avec l'infra existante de Quentin).

## 11. Couche méta

La méta améliore automatiquement, sans validation humaine, les prompts, les règles de routage, les valeurs courantes des paramètres à deux niveaux et le schéma (en additif) ; un filet mécanique de shadow mode et de rollback remplace tout juge supplémentaire (TRANCHÉ).

| Élément | Fonctionnement | Statut |
| --- | --- | --- |
| Évaluateur | Détecte les échecs après chaque exécution ou par petits lots | TRANCHÉ |
| Critique TextGrad | Produit un gradient textuel sur un échec ; famille ≠ jugé | TRANCHÉ |
| Carnet d'erreurs REMO | Mémoire RAG des traces d'échec accumulées | TRANCHÉ |
| Optimiseur | Réécrit par lot large ; échec critique signalé par le superviseur → déclenchement immédiat | TRANCHÉ |
| Shadow mode | Nouveau prompt rejoué en parallèle sur les mêmes données, sans décision réelle ; bascule si métriques égales ou meilleures | TRANCHÉ |
| Équivalent pour les méthodes | Le backtest pré-filtre (pas de shadow possible sans trader) | TRANCHÉ |
| Rollback | Retour automatique à la version précédente si dégradation après bascule | TRANCHÉ |
| Paramètres à deux niveaux | Écrit seulement la valeur courante, ramenée dans les bornes fixes (cahier 1, I3) | TRANCHÉ |

À trancher : taille des lots ; définition de « échec critique » ; métriques et seuil de comparaison du shadow mode ; fenêtre d'observation et définition de « dégradation » pour le rollback ; stockage des versions (PROPOSÉ : dépôt Git dédié, un commit par `MetaChange`) ; bibliothèques TextGrad et implémentation REMO à vérifier dans leurs sources officielles.

Ce lot vient en dernier : la méta a besoin d'un historique réel pour optimiser.

## 12. Exploitation

Tout tourne en conteneurs Docker ; l'hébergement précis n'a pas encore été décidé pour ce projet.

| Sujet | Exigence | Statut |
| --- | --- | --- |
| Hébergement | Candidat : l'infra existante (Dokploy sur VPS Hostinger, ou NAS Synology) | À TRANCHER |
| Disponibilité | Le filet de secours (cahier 1) doit tourner en continu ; une machine qui dort l'interrompt | PROPOSÉ (exclut un portable) |
| Secrets | Clé Revolut X depuis `pass` vers le seul garde-fou ; clés OpenRouter et LiteLLM dans des secrets Docker distincts | clé Revolut X TRANCHÉ ; reste PROPOSÉ |
| Réseau | Seul le garde-fou sort vers Revolut X ; seul LiteLLM sort vers les providers | PROPOSÉ |
| Reprise | Redémarrage automatique des conteneurs ; reprise du graphe depuis le dernier checkpoint ; reconstruction du registre depuis l'API courtier | PROPOSÉ |
| Mises à jour | Déploiement d'une nouvelle version uniquement après STOP de Quentin ; jamais pendant une position ouverte sans filet actif | PROPOSÉ |
| Code | Dépôt Git privé (Gitea), CI des tests des deux cahiers | PROPOSÉ |

## 13. Plan de construction par lots

Huit lots, chacun confié à une session Claude Code distincte ; les lots L0 à L3 sont testables sans aucun LLM réel. Ordre validé par Quentin le 2026-10-03 (TRANCHÉ), avec repli mécanique sur le changement de méthode tant que le superviseur n'est pas livré.

| Lot | Contenu | Prérequis | Tests de sortie | STOP avant |
| --- | --- | --- | --- | --- |
| L0 | Cahier 1 : mécanique déterministe | Q1–Q6 du cahier 1 tranchés | Ceux du cahier 1, dont l'ordre réel minuscule | Ordre réel |
| L1 | Contrats (section 4) en schémas versionnés | L0 | Validation, rejet des sorties invalides, ajout additif seulement | — |
| L2 | Automate orchestrateur (section 5) avec stubs à la place des LLM | L1 | Chaque transition déclenchée par un événement simulé ; état inconnu → conseiller stub | — |
| L3 | Graphe LangGraph + cycle de replan avec agents factices ; backtest pré-filtre | L2 | Les 3 classes d'erreur ; compteurs bornés ; reprise depuis checkpoint ; backtest reproductible | — |
| L4 | Routage : LiteLLM + Jev + un premier conteneur d'abonnement. Placé avant les prompts : tout appel LLM passe par le routeur | L1 | Appel réel à chaque palier ; contrainte de famille respectée ; repli si Jev indisponible | Premier appel payant OpenRouter |
| L5 | Interview relentless, puis prompts planificateur et exécutant ; Langfuse dès ce lot pour tracer le premier trade réel. Repli mécanique : `METHOD_CHANGE_REQUIRED` → arrêt des nouveaux ordres + notification à Quentin, jusqu'à L6 | L3, L4 | Sorties valides sur scénarios figés ; traces visibles ; repli déclenché par un changement simulé | Premier trade réel autonome |
| L6 | Superviseur (2 chemins) et conseiller orchestrateur ; retrait du repli de L5 | L5 | Escalade technique et changement de méthode simulés puis réels | Retrait du repli et déploiement continu |
| L7 | Couche méta | L6 + historique réel suffisant (seuil À TRANCHER) | Shadow mode et rollback sur une dégradation provoquée | Première bascule automatique |

Chaque lot livre aussi : sa mise à jour de `CLAUDE.md`, ses ADR, et la liste des questions remontées à Quentin.

## 14. Points ouverts

P1 est structurant et doit être tranché avant L1 ; les autres se tranchent au plus tard au lot indiqué.

| # | Question | Bloque | Source |
| --- | --- | --- | --- |
| P1 | La méthode est-elle un jeu de règles exécutées par du code (l'exécutant LLM se réduit alors à appliquer et annoter), ou l'exécutant décide-t-il chaque trade en lisant le marché ? Dans le second cas, le backtest ne teste pas ce qui trade réellement | L1, L3, L5 | Quentin |
| P2 | Texte final de l'objectif global | L2, L5 | Quentin |
| P3 | Superviseur choisit la méthode suivante, planificateur la détaille : interprétation à confirmer | L2, L6 | Quentin |
| P4 | Liste fermée des actions du conseiller orchestrateur | L2 | Quentin |
| P5 | Valeurs des compteurs retry, patch, replan ; règles de classification des erreurs | L3 | Littérature / Quentin |
| P6 | Données historiques, critère de rejet et garde-fou de surajustement du backtest | L3 | Littérature |
| P7 | Table palier → modèles et familles ; épuisement de quota ; repli si Jev indisponible | L4 | Leaderboards / Quentin |
| P8 | Conformité de l'usage des abonnements en conteneur | L4 | Conditions des providers |
| P9 | Langfuse confirmé, hébergement et budget | L5 | Quentin |
| P10 | Hébergement global du système (VPS, NAS) | L0 en réel | Quentin |
| P11 | Taille des lots méta, « échec critique », métriques shadow, « dégradation » | L7 | Littérature |
| P12 | Historique minimal avant d'activer la méta | L7 | Littérature |
