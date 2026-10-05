# Cahier des charges — Mécanique déterministe (trading multi-agents)

Oct 3, 2026 · @Quentin Veys

## 1. Objet et périmètre

Faire construire par Claude Code la couche déterministe (code pur, zéro LLM) qui encadre tout ordre réel sur Revolut X. Elle doit être testable intégralement sans aucun agent branché, puis validée par un vrai ordre minuscule.

Convention de statut utilisée dans tout le document : **TRANCHÉ** = décision de Quentin (directe ou par acceptation d'une recommandation) ; **DÉFAUT** = valeur par défaut posée pour clôturer le cahier, configurable, à recalibrer sur données réelles ; **PROPOSÉ** = choix de conception de ce cahier ; **À TRANCHER** = donnée manquante, ne pas inventer.

| Dans le périmètre | Hors périmètre (phases suivantes) |
| --- | --- |
| Validation pré-ordre (garde-fous de risque) | Agents LLM : planificateur, exécutant, superviseur, couche méta |
| Dimensionnement (bootstrap, Kelly) | Routage modèles (Jev, LiteLLM) |
| Filet de secours du stop | Observabilité LLM (Langfuse) |
| Registre des trades + contrôle de cohérence | Backtest pré-filtre |
| Évaluation de méthode : SPRT, drawdown, verrou, survie | Dashboard humain |
| Sécurité clé API + notifications | Automate orchestrateur (voir points ouverts) |

Langage : Python — DÉFAUT (cohérence avec LangGraph, retenu pour la couche agents). Exigences : Decimal pour tout montant, prix et quantité (jamais float) ; mypy --strict en CI ; aucune dépendance LLM ni LangGraph dans le conteneur garde-fou. Le contrat de l'API Revolut X n'est pas spécifié ici : Claude Code doit le lire dans la documentation officielle, jamais le supposer.

## 2. Invariants non négociables

Aucun test, aucune configuration et aucune couche supérieure ne peut violer ces règles ; chacune doit être couverte par au moins un test.

| # | Invariant | Statut |
| --- | --- | --- |
| I1 | Aucun appel LLM dans le chemin de décision d'un module de ce document | TRANCHÉ |
| I2 | Seul le conteneur garde-fou détient la clé Revolut X ; tout ordre passe par son API interne | TRANCHÉ |
| I3 | Bornes fixes en configuration immuable au runtime ; la couche méta n'écrit qu'une valeur courante, ramenée (clamp) dans les bornes | TRANCHÉ |
| I4 | Solde, ordres, prix et frais viennent de l'API courtier, jamais d'un rapport de l'exécutant | TRANCHÉ |
| I5 | Perte maximale par ordre ≤ 1 % du capital courant, recalculé à chaque ordre | TRANCHÉ |
| I6 | Règles de décision statistiques figées avant la première donnée d'une méthode | TRANCHÉ |
| I7 | Arrêt dur uniquement quand le capital est perdu | TRANCHÉ |
| I8 | Fail-closed : donnée manquante, périmée ou API injoignable → ordre refusé | PROPOSÉ |
| I9 | Registre append-only : aucune ligne modifiée ni supprimée | PROPOSÉ |

## 3. Architecture

Les six modules vivent dans un seul conteneur, seul à détenir la clé et à parler à Revolut X ; les agents n'y accèdent que par l'API interne (TRANCHÉ).

&#91;embedded content: architecture de la mécanique déterministe · 6 modules dans un conteneur\]

En pointillés : composants LLM hors périmètre, remplacés en test par des stubs qui envoient des intentions et consomment les événements (`LEDGER_ANOMALY`, `SAFETY_NET_FIRED`, `METHOD_CHANGE_REQUIRED`, `METHOD_VALIDATED`).

## 4. Module 1 — Validation pré-ordre

Chaque intention d'ordre traverse une suite de règles ordonnées ; la première violation renvoie un refus avec code, sans appel au courtier.

Entrée (PROPOSÉ) : `OrderIntent { method_id, pair, side, stop_price, annotation }`. L'exécutant ne fournit pas la quantité : elle est calculée par le Module 2, conformément à « jamais la confiance auto-déclarée de l'exécutant ».

| Ordre | Règle | Calcul | Code refus | Statut |
| --- | --- | --- | --- | --- |
| R0 | Fraîcheur des données | Solde, prix, carnet lus à l'API depuis < N s | `STALE_DATA` | DÉFAUT : N = 10 s |
| R1 | Méthode active et non verrouillée en sortie | `method_id` = méthode active ; aucun changement de méthode en cours | `METHOD_INACTIVE` | TRANCHÉ |
| R2 | Compatibilité méthode | paire et fréquence dans ce que la méthode a déclaré | `METHOD_INCOMPATIBLE` | TRANCHÉ |
| R3 | Paire autorisée | spread < 0,2 % et volume ≥ V\_min | `PAIR_FILTER` | DÉFAUT : V\_min = 100 000 € de volume sur 24 h |
| R4 | Stop obligatoire | `stop_price` présent et du bon côté du prix | `NO_STOP` | TRANCHÉ |
| R5 | Risque par ordre | Σ sur positions ouvertes + ordre de qté × (\|entrée − stop\| + f × (entrée + stop)) ≤ 1 % × capital courant | `RISK_CAP` | TRANCHÉ (frais inclus, Q6 ; risque cumulé des positions ouvertes, Q4 — crypto fortement corrélées au BTC, pire cas corrélation = 1) |
| R6 | Plafond de mise | qté × entrée ≤ p\_mise × capital courant | `STAKE_CAP` | TRANCHÉ |
| R7 | Plafond d'exposition | Σ positions ouvertes + mise ≤ p\_expo × capital | `EXPOSURE_CAP` | TRANCHÉ sur recommandation (Q4) : p\_expo ∈ \[25 %, 50 %\], départ 25 % (protège du gap à travers le stop) |
| R8 | État de survie | aucun seuil de survie franchi, pas d'arrêt dur | `SURVIVAL_STATE` | TRANCHÉ |

Sortie : `ACCEPT` → envoi de l'ordre puis pose immédiate du stop natif ; échec de pose du stop = position confiée au Module 3. Chaque décision (accept ou refus) est journalisée avec les valeurs utilisées.

## 5. Module 2 — Dimensionnement

La quantité découle du risque et de la distance du stop, jamais d'un montant choisi par un agent ; une seule bascule bootstrap → Kelly à 30 trades de la méthode.

```latex
\text{qté} = \min\left( \frac{r \cdot C}{|P_{entrée} - P_{stop}| + f \cdot (P_{entrée} + P_{stop})},\ \frac{m \cdot C}{P_{entrée}} \right)
```

C = capital courant lu au courtier ; r = fraction de risque ; m = fraction de mise ; f = taux de frais par côté. Frais inclus dans le risque : TRANCHÉ (la perte au stop, frais compris, ne dépasse pas r·C). f = taux taker appliqué aux deux côtés, lu à l'API : PROPOSÉ (hypothèse prudente, l'entrée pouvant être maker à 0 %). Le glissement d'exécution du stop n'est pas couvert par cette formule (voir Q7 et Module 3).

| Phase | r (risque) | m (mise) | Statut |
| --- | --- | --- | --- |
| Bootstrap (< 30 trades de la méthode) | 1 % | 10 % (bas de fourchette) | TRANCHÉ |
| Kelly (≥ 30 trades) | min(1 %, ½·f\*) | p\_mise courant (10–25 %) | TRANCHÉ ; demi-Kelly empirique (Q5) |

Kelly — TRANCHÉ sur recommandation (Q5) : f\* = Kelly empirique, valeur de f qui maximise la moyenne de ln(1 + f·Rᵢ) sur les multiples R nets des trades de la méthode active depuis son activation ; r = min(1 %, ½·f\*) (demi-Kelly : MacLean, Thorp, Ziemba 2010 ; Benter 1994). f\* ≤ 0 après 30 trades → `METHOD_CHANGE_REQUIRED` (sinon r = 0 bloque le SPRT). Kelly sous contrainte de drawdown (Busseti, Ryu, Boyd 2016) : amélioration ultérieure, hors L0. DÉFAUT : arrondi à l'inférieur au pas de quantité et à la taille minimale d'ordre Revolut X (ordre sous le minimum = refus `BELOW_MIN_SIZE`).

## 6. Module 3 — Filet de secours du stop

Un processus déterministe en boucle continue garantit qu'aucune position ouverte ne reste sans stop : si le stop natif a disparu sans exécution, il vend au marché (TRANCHÉ).

Boucle, à chaque tick (DÉFAUT : 5 s, à respecter sous les limites de débit de l'API) :

1. Lire à l'API les positions détenues et les ordres actifs.
2. Pour chaque position, chercher son stop natif actif.
3. Stop présent → rien.
4. Stop absent → relire l'historique des exécutions : stop exécuté → clôturer la position au registre, rien d'autre.
5. Stop absent et non exécuté → vente au marché de la quantité détenue, puis notification et événement `SAFETY_NET_FIRED` au superviseur.

Exigences (PROPOSÉ) :

- Idempotence : une vente du filet porte un identifiant client dérivé de la position ; un second tick ne revend jamais.
- Course stop/filet : l'étape 4 précède toujours l'étape 5 ; en spot, une vente sur solde insuffisant doit être traitée comme « déjà clôturé », pas comme une erreur fatale.
- Courtier injoignable : aucune action possible, donc notification immédiate et blocage de tout nouvel ordre (I8).
- Le filet tourne dans le même conteneur que le garde-fou (seul détenteur de la clé, I2) mais dans un processus séparé : une panne du validateur ne l'arrête pas.

## 7. Module 4 — Registre des trades et contrôle de cohérence

Le registre est reconstruit depuis l'historique d'ordres de l'API Revolut X ; l'exécutant n'écrit que des annotations, jointes par identifiant (TRANCHÉ).

| Source | Champs | Écrit par |
| --- | --- | --- |
| Courtier | id ordre, id client, paire, côté, type, quantité exécutée, prix, horodatage, commission | Processus de reconstruction |
| Courtier (calculé) | spread à l'envoi, solde après ordre, PnL net par trade | Processus de reconstruction |
| Exécutant | method\_id, signal, justification | API interne, au moment de l'intention |

Clé de jointure (PROPOSÉ) : l'API interne génère l'identifiant client de chaque ordre et le transmet au courtier ; l'annotation est stockée sous ce même identifiant.

Contrôle de cohérence, à chaque reconstruction — toute divergence = événement `LEDGER_ANOMALY` au superviseur :

| Cas | Exemple |
| --- | --- |
| Ordre courtier sans annotation | ordre passé hors API interne, vente du filet non tracée |
| Annotation sans ordre courtier | intention acceptée mais ordre jamais arrivé |
| Écart de valeurs | quantité ou côté différent entre intention et exécution |

Stockage : base locale append-only, SQLite — PROPOSÉ. Définition d'un « trade » pour le PnL et le SPRT : TRANCHÉ — un trade = un aller-retour complet (ouverture puis fermeture de la position) ; les exécutions partielles d'un même ordre sont regroupées en un seul remplissage au prix moyen pondéré par la quantité. Seul un trade fermé alimente le PnL, le compteur de 30 trades et le SPRT.

## 8. Module 5 — Évaluation de méthode

Le moment d'un changement de méthode est décidé mécaniquement ; le superviseur ne choisit que la méthode suivante (TRANCHÉ). Le module émet `METHOD_CHANGE_REQUIRED { reason }`, `METHOD_VALIDATED` ou rien.

| Déclencheur | Condition | Actif à partir de | Statut |
| --- | --- | --- | --- |
| Seuil de survie | capital ≤ (1 − s) × M, M = capital maximal atteint (plancher glissant, Grossman–Zhou 1993) ; s ∈ \[30 %, 50 %\], départ 40 %, affinage méta | trade 1 | TRANCHÉ ; bornes sur recommandation (Q3) |
| SPRT borne basse | LLR ≤ B | trade 30 | TRANCHÉ |
| Drawdown méthode | (pic − équité) / pic ≥ d, d ∈ \[15 %, 25 %\], départ 20 % | trade 30 (verrou) | TRANCHÉ ; DÉFAUT : actif dès le trade 1 (priorité : ne pas perdre le capital) |
| Kelly nul | f\* ≤ 0 (aucun avantage mesuré) | trade 30 | TRANCHÉ sur recommandation (Q5) |
| SPRT borne haute | LLR ≥ A → méthode validée, pas de changement | trade 30 | TRANCHÉ |
| Troncature | 300 trades sans borne franchie | trade 300 | DÉFAUT : aucun verdict statistique ; avantage non démontré → METHOD\_CHANGE\_REQUIRED |

SPRT en t séquentiel (Rushton 1950, variance inconnue), rapport de vraisemblance cumulé après chaque trade dès le trade 1, décision lue seulement à partir du trade 30. Avec les taux tranchés — 5 % de garder une méthode mauvaise, 20 % d'abandonner une bonne — les bornes de Wald sont :

```latex
A = \ln\frac{1 - 0{,}20}{0{,}05} = \ln 16 \approx 2{,}773 \qquad B = \ln\frac{0{,}20}{1 - 0{,}05} \approx -1{,}558
```

Observation = PnL net du trade (frais inclus, Q6) divisé par le risque engagé (multiple R). H0 : moyenne = 0 (méthode sans avantage) ; H1 : moyenne = d\_min × σ. d\_min = plus petit effet dont le nombre moyen de trades avant décision reste ≤ 300, calibré par le Monte-Carlo du plan de test. TRANCHÉ sur recommandation (Q2). Robustesse à la non-normalité établie par simulation (Schnuerch & Erdfelder 2020) ; non garantie si l'avantage de la méthode varie dans le temps (changement de régime). Bornes et d\_min figés à l'activation de la méthode (I6).

Conséquences d'un seuil de survie franchi (TRANCHÉ) : changement de méthode forcé, notification à Quentin, aucun nouvel ordre de la méthode sortante. Capital perdu → arrêt dur ; DÉFAUT : capital perdu = capital ne permettant plus un ordre à la taille minimale Revolut X qui respecte R5.

## 9. Module 6 — Sécurité de la clé API et notifications

La clé Revolut X a des droits trading uniquement, est injectée depuis `pass` dans le seul conteneur garde-fou, et l'exécutant ne la voit jamais (TRANCHÉ).

| Exigence | Détail | Statut |
| --- | --- | --- |
| Droits de la clé | trading seul, aucun retrait ; vérifié avant tout ordre réel | TRANCHÉ ; méthode de vérification À TRANCHER (selon ce qu'expose l'API) |
| Injection | lue depuis `pass` au démarrage, passée en secret Docker, jamais en variable loggée ni en image | TRANCHÉ (secret Docker PROPOSÉ) |
| Isolation | conteneur garde-fou seul à avoir l'accès réseau sortant vers Revolut X ; l'exécutant n'atteint que l'API interne | PROPOSÉ |
| Journaux | aucune valeur de clé ni signature dans les logs ; test automatique de non-fuite | PROPOSÉ |

Notifications à Quentin, sans dashboard (TRANCHÉ ; DÉFAUT : mail) :

| Événement | Statut |
| --- | --- |
| Seuil de survie franchi | TRANCHÉ |
| Arrêt dur (capital perdu) | PROPOSÉ |
| Filet de secours déclenché | PROPOSÉ |
| Courtier injoignable au-delà d'un délai | PROPOSÉ |

## 10. Paramètres

Tous les paramètres vivent dans une configuration versionnée : bornes en lecture seule, valeur courante écrite par la couche méta et ramenée dans les bornes (I3).

| Paramètre | Borne basse | Borne haute | Valeur de départ | Affiné par la méta | Statut |
| --- | --- | --- | --- | --- | --- |
| Risque max par ordre | — | 1 % du capital | 1 % | non | TRANCHÉ |
| Plafond de mise p\_mise | 10 % | 25 % | 17,5 % (milieu) ; 10 % en bootstrap | oui | TRANCHÉ |
| Plafond d'exposition p\_expo | 25 % | 50 % | 25 % | oui | TRANCHÉ sur recommandation (Q4) |
| Drawdown méthode d | 15 % | 25 % | 20 % | oui | TRANCHÉ (départ au milieu PROPOSÉ) |
| Seuil de survie | 30 % sous le max | 50 % sous le max | 40 % | oui | TRANCHÉ sur recommandation (Q3) |
| Nombre min. de trades | 30 | 300 | 30 | oui | TRANCHÉ |
| SPRT : garder une mauvaise méthode | — | — | 5 % | non | TRANCHÉ |
| SPRT : abandonner une bonne méthode | — | — | 20 % | non | TRANCHÉ |
| SPRT : effet minimal d\_min | — | — | calibré par Monte-Carlo (ASN ≤ 300) | non (figé à l'activation) | TRANCHÉ |
| Spread max paire | — | 0,2 % | 0,2 % | non | TRANCHÉ |
| Volume min paire V\_min | — | — | 100 000 € / 24 h | oui | DÉFAUT |
| Bascule bootstrap → Kelly | — | — | 30 trades | non | TRANCHÉ |

Donnée mesurée de référence : Revolut X, BTC-EUR, spread \~0,04 %, frais 0 % maker / 0,09 % taker (relevés par Quentin, à reconfirmer à l'API avant le premier ordre).

## 11. Stratégie de test

Trois niveaux successifs ; un niveau ne démarre que si le précédent est vert, et le niveau 3 exige un STOP explicite de Quentin avant exécution.

| Niveau | Cible | Contenu minimal |
| --- | --- | --- |
| 1. Unitaires purs | Modules 1, 2, 5 | Chaque règle R0–R8 en accept et refus ; formule de quantité ; LLR et bornes SPRT ; drawdown ; clamp des bornes |
| 1 bis. Propriétés | Modules 1, 2 | Test à base de propriétés (PROPOSÉ : Hypothesis) : pour toute entrée, perte au stop ≤ 1 % du capital et mise ≤ p\_mise |
| 1 ter. Monte-Carlo SPRT | Module 5 | Séries synthétiques sous H0 et H1 : taux d'erreur observés proches de 5 % et 20 % |
| 2. Simulateur Revolut X | Modules 1–6 | Faux serveur reproduisant le contrat de l'API officielle (voir scénarios) |
| 3. Réel minuscule | Chaîne complète | Un ordre BTC-EUR à la taille minimale, stop natif posé, registre reconstruit, cohérence vérifiée, frais réels relevés |

Scénarios obligatoires du simulateur :

1. Stop natif annulé par le courtier en marché rapide → le filet vend au marché une seule fois.
2. Stop exécuté juste avant le tick du filet → aucune vente supplémentaire.
3. Échec de pose du stop après un ordre exécuté → le filet couvre la position.
4. API en timeout ou erreur 5xx → refus d'ordre (I8) et notification.
5. Ordre au courtier sans annotation, et inversement → `LEDGER_ANOMALY`.
6. Exécution partielle → quantités et PnL justes au registre.
7. Spread > 0,2 % → refus `PAIR_FILTER`.
8. Seuil de survie franchi → `METHOD_CHANGE_REQUIRED`, notification, plus aucun ordre de la méthode.
9. Logs inspectés : aucune trace de la clé.

Préalables au niveau 3 : droits de la clé vérifiés (trading seul), taille minimale d'ordre et frais relus dans la documentation officielle.

## 12. Critères d'acceptation

La mécanique est livrée quand toutes les cases sont cochées ; les agents LLM ne sont branchés qu'après.

- [ ] Invariants I1–I9 couverts chacun par au moins un test nommé
- [ ] Niveaux de test 1, 1 bis, 1 ter et 2 verts en CI, sans réseau ni LLM
- [ ] Les 9 scénarios du simulateur passent
- [ ] Aucune valeur inventée hors statut DÉFAUT : chaque DÉFAUT est un paramètre configurable, tracé, recalibrable ; seules les vérifications de la documentation Revolut X restent bloquantes avant le premier ordre réel
- [ ] Droits de la clé vérifiés (trading seul) et consignés
- [ ] STOP de Quentin obtenu, puis ordre réel minuscule exécuté avec stop natif
- [ ] Registre reconstruit après l'ordre réel, contrôle de cohérence sans anomalie, frais réels enregistrés

## 13. Points ouverts

Q1 à Q6 bloquent le cœur des calculs ; Q7 à Q14 peuvent être tranchés pendant la construction, chacun derrière un paramètre qui empêche le démarrage tant qu'il est vide.

| # | Question | Bloque | Source de réponse |
| --- | --- | --- | --- |
| Q1 | Définition d'un « trade » (aller-retour, exécutions partielles) | Modules 4, 5 | TRANCHÉ (Quentin) : aller-retour complet, exécutions partielles regroupées au prix moyen pondéré |
| Q2 | Modèle de vraisemblance du SPRT et formulation H0/H1 | Module 5 | TRANCHÉ sur recommandation de Claude (littérature) |
| Q3 | Bornes du seuil de survie et règle de suivi de la croissance | Modules 1, 5 | TRANCHÉ sur recommandation de Claude (forme : littérature ; valeurs : choix) |
| Q4 | Bornes du plafond d'exposition totale | Module 1 | TRANCHÉ sur recommandation de Claude (forme : littérature ; valeurs : choix) |
| Q5 | Variante de Kelly, fenêtre, cas f ≤ 0 | Module 2 | TRANCHÉ sur recommandation de Claude (littérature) |
| Q6 | Frais inclus ou non dans le risque de 1 % | Modules 1, 2 | TRANCHÉ (Quentin) : frais inclus |
| Q7 | Volume minimal V\_min des paires | Module 1 | DÉFAUT : 100 000 € / 24 h |
| Q8 | Comportement à la troncature de 300 trades | Module 5 | DÉFAUT : pas de verdict → changement de méthode |
| Q9 | Drawdown actif avant 30 trades ou soumis au verrou | Module 5 | DÉFAUT : actif dès le trade 1 |
| Q10 | Définition chiffrée de « capital perdu » | Module 5 | DÉFAUT : plus d'ordre minimal possible sous R5 |
| Q11 | Intervalle du filet, fraîcheur N des données | Modules 1, 3 | DÉFAUT : filet 5 s, N = 10 s (sous limites API) |
| Q12 | Canal de notification (mail, push) | Module 6 | DÉFAUT : mail |
| Q13 | Automate orchestrateur inclus dans cette phase ou non | Périmètre | Résolu : automate en L2 du cahier 2 |
| Q14 | Validation des choix PROPOSÉ (Python, SQLite, Hypothesis, secret Docker, isolation réseau) | Tous | DÉFAUT : tous retenus + Decimal, mypy --strict, zéro dépendance LLM |
