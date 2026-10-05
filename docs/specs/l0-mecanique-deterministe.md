## Problem Statement

Quentin veut une couche déterministe, sans LLM, qui encadre tout ordre réel sur Revolut X avant qu'un agent ne soit branché. Aujourd'hui le dépôt n'a aucun code : rien ne refuse un ordre trop risqué, rien ne pose un stop, rien ne reconstruit un registre depuis le courtier, et rien n'empêche une clé API de fuir. Le capital visé est d'environ 100 €. La priorité est de ne pas le perdre.

## Solution

Livrer le lot L0 : les six modules du cahier 1 dans un seul conteneur garde-fou, exposés par une API HTTP interne authentifiée par jeton. Chaque intention d'ordre est validée, dimensionnée, puis soit refusée avec un code, soit acceptée. Le mode à blanc est activé par défaut : la validation est complète, aucun ordre, stop ou vente n'est envoyé au courtier.

Le filet de secours maintient un stop sur chaque position réelle. Le registre est reconstruit depuis l'historique courtier. Le changement de méthode est mécanique. La clé a des droits de trading seuls, n'existe que dans ce conteneur, et n'apparaît dans aucun log.

Avant tout code qui parle à Revolut X, la documentation officielle courante est lue et consignée dans une ADR. Tout écart avec le cahier 1 remonte à Quentin et bloque le code concerné. Le premier ordre réel minuscule n'est pas exécuté dans cette spec : il attend un STOP explicite de Quentin.

## User Stories

1. En tant que Quentin, je veux que le système démarre en mode à blanc, afin qu'aucun ordre n'atteigne Revolut X tant que je ne l'ai pas décidé.
2. En tant que Quentin, je veux qu'un paramètre vide marqué à trancher fasse échouer le démarrage avec le nom du paramètre, afin qu'aucune valeur plausible ne soit inventée.
3. En tant que Quentin, je veux que chaque défaut du cahier 1 soit un paramètre configurable et non une constante en dur, afin de le recalibrer sur des données réelles.
4. En tant que Quentin, je veux une ADR écrite depuis la documentation officielle Revolut X avant le code courtier, afin de fixer le stop natif, la taille minimale, le pas de quantité, les droits de clé, les limites de débit et la restriction par IP.
5. En tant que Quentin, je veux que tout écart entre cette ADR et le cahier 1 me soit remonté avant le code concerné, afin de trancher moi-même.
6. En tant qu'exécutant, je veux soumettre une intention d'ordre sans quantité, afin que le garde-fou calcule la taille et que ma confiance auto-déclarée ne fixe jamais la mise.
7. En tant qu'exécutant, je veux un refus avec un code et sans appel courtier dès la première règle violée, afin de savoir pourquoi l'ordre n'est pas parti.
8. En tant qu'exécutant, je veux un jeton pour appeler l'API interne, afin qu'un appel sans jeton soit rejeté.
9. En tant que Quentin, je veux que seul le conteneur garde-fou détienne la clé et le réseau sortant vers Revolut X, afin qu'aucun autre processus ne puisse passer un ordre.
10. En tant que Quentin, je veux que la clé soit lue depuis pass au démarrage puis injectée en secret Docker, afin qu'elle ne soit ni dans le code, ni dans l'image, ni dans les logs.
11. En tant que Quentin, je veux un test automatique qui échoue si une valeur de clé ou une signature apparaît dans les logs, afin de tenir l'exigence de non-fuite.
12. En tant que Quentin, je veux que les droits de la clé soient vérifiés trading seul, sans retrait, avant tout ordre réel, afin de ne pas envoyer d'argent hors du compte.
13. En tant que garde-fou, je veux refuser avec `STALE_DATA` si le solde, le prix ou le carnet a plus de N secondes, afin de ne pas décider sur une donnée périmée.
14. En tant que Quentin, je veux N configurable, départ 10 secondes, afin de le recaler sur les limites de débit réelles.
15. En tant que garde-fou, je veux refuser avec `METHOD_INACTIVE` si l'intention ne vise pas la méthode active ou si un changement de méthode est en cours, afin qu'une seule méthode trade à la fois.
16. En tant que garde-fou, je veux refuser avec `METHOD_INCOMPATIBLE` si la paire ou la fréquence sort de ce que la méthode a déclaré, afin de ne pas exécuter hors mandat.
17. En tant que garde-fou, je veux refuser avec `PAIR_FILTER` si le spread est supérieur ou égal à 0,2 % ou si le volume 24 h est sous le minimum, afin d'écarter les paires illiquides.
18. En tant que Quentin, je veux le volume minimum configurable, départ 100 000 € sur 24 h, afin de le recalibrer.
19. En tant que garde-fou, je veux refuser avec `NO_STOP` si le stop est absent ou du mauvais côté du prix, afin qu'aucun ordre n'existe sans stop.
20. En tant que garde-fou, je veux refuser avec `RISK_CAP` si la perte au stop, frais inclus, cumulée avec les positions ouvertes, dépasse 1 % du capital courant, afin de tenir le plafond par ordre.
21. En tant que garde-fou, je veux sommer le risque des positions ouvertes comme si elles étaient corrélées à 1, afin de traiter le pire cas crypto corrélé au BTC.
22. En tant que garde-fou, je veux refuser avec `STAKE_CAP` si la mise dépasse la fraction de mise fois le capital, afin de plafonner la taille indépendamment du stop.
23. En tant que garde-fou, je veux refuser avec `EXPOSURE_CAP` si les positions ouvertes plus la mise dépassent la fraction d'exposition fois le capital, afin de limiter le gap à travers le stop.
24. En tant que Quentin, je veux la fraction d'exposition bornée de 25 % à 50 %, départ 25 %, afin que la méta future ne sorte pas de cette plage.
25. En tant que garde-fou, je veux refuser avec `SURVIVAL_STATE` si un seuil de survie est franchi ou si l'arrêt dur est actif, afin qu'aucun nouvel ordre ne parte dans cet état.
26. En tant que garde-fou, je veux, sur acceptation hors mode à blanc, envoyer l'ordre puis poser tout de suite le stop natif, afin que la position ne reste pas nue.
27. En tant que filet, je veux prendre la position si la pose du stop échoue après un ordre exécuté, afin qu'elle ne reste pas sans protection.
28. En tant que Quentin, je veux chaque acceptation et chaque refus journalisés avec les valeurs utilisées, afin de reconstruire la décision.
29. En tant que garde-fou, je veux calculer la quantité à partir du risque, de la distance au stop et des frais, puis la plafonner par la fraction de mise, afin que la taille vienne de la formule et non d'un agent.
30. En tant que garde-fou, je veux utiliser des décimaux pour tout montant, prix et quantité, afin qu'un flottant ne fausse ni le risque ni le registre.
31. En tant que garde-fou, je veux, sous 30 trades de la méthode, risquer 1 % et mettre 10 % du capital, afin de tenir la phase bootstrap.
32. En tant que garde-fou, je veux, à partir de 30 trades, risquer le minimum entre 1 % et un demi-Kelly empirique, afin de ne monter la mise que si un avantage est mesuré.
33. En tant que garde-fou, je veux calculer le Kelly empirique sur les multiples R nets des trades de la méthode active depuis son activation, afin que la fenêtre soit celle tranchée.
34. En tant que garde-fou, je veux émettre `METHOD_CHANGE_REQUIRED` si le Kelly empirique est négatif ou nul après 30 trades, afin de ne pas bloquer le test séquentiel avec un risque à zéro.
35. En tant que garde-fou, je veux arrondir la quantité à l'inférieur au pas du courtier, afin de ne jamais dépasser le risque calculé.
36. En tant que garde-fou, je veux refuser avec `BELOW_MIN_SIZE` si la quantité est sous la taille minimale, afin de ne pas envoyer un ordre que le courtier rejetterait.
37. En tant que garde-fou, je veux lire le taux taker à l'API et l'appliquer des deux côtés dans le risque, afin que la perte au stop, frais compris, ne dépasse pas la fraction de risque.
38. En tant que filet, je veux, toutes les 5 secondes par défaut, lire les positions et les ordres actifs, afin qu'aucune position réelle ne reste sans stop.
39. En tant que filet, je veux ne rien faire si le stop natif de la position est actif, afin de ne pas doubler le courtier.
40. En tant que filet, je veux, si le stop est absent mais exécuté dans l'historique, clôturer la position au registre et ne pas vendre, afin d'éviter une seconde vente.
41. En tant que filet, je veux, si le stop est absent et non exécuté, vendre au marché la quantité détenue et émettre `SAFETY_NET_FIRED`, afin de fermer la position nue.
42. En tant que filet, je veux qu'une vente de filet porte un identifiant client dérivé de la position, afin qu'un second tick ne revende jamais.
43. En tant que filet, je veux traiter une vente spot sur solde insuffisant comme une position déjà clôturée, afin qu'une course stop/filet ne soit pas une erreur fatale.
44. En tant que filet, je veux, si le courtier est injoignable, ne pas inventer d'action, notifier, et bloquer tout nouvel ordre, afin de rester fail-closed.
45. En tant que Quentin, je veux que le filet tourne dans un processus séparé du validateur, dans le même conteneur, afin qu'une panne du validateur ne retire pas le filet.
46. En tant que Quentin, je veux l'intervalle du filet configurable, afin de le garder sous les limites de débit consignées dans l'ADR.
47. En tant que registre, je veux me reconstruire depuis l'historique d'ordres du courtier, afin que le solde, les prix, les quantités et les frais ne viennent jamais d'un rapport d'exécutant.
48. En tant qu'exécutant, je veux attacher method_id, signal et justification à l'identifiant client de l'ordre, afin que l'annotation survive sans écrire les faits financiers.
49. En tant que registre, je veux regrouper les exécutions partielles d'un même ordre en un remplissage au prix moyen pondéré par la quantité, afin qu'un trade soit un aller-retour complet.
50. En tant que registre, je veux n'alimenter le PnL, le compteur de 30 trades et le SPRT qu'avec un trade fermé, afin de ne pas compter une position encore ouverte.
51. En tant que registre, je veux émettre `LEDGER_ANOMALY` s'il y a un ordre courtier sans annotation, une annotation sans ordre, ou un écart de quantité ou de côté, afin que le superviseur voie la divergence.
52. En tant que Quentin, je veux un registre append-only en SQLite, afin qu'aucune ligne ne soit modifiée ni supprimée.
53. En tant qu'évaluateur, je veux émettre `METHOD_CHANGE_REQUIRED` quand le capital passe sous (1 − s) fois le capital maximal atteint, afin de forcer le changement dès le premier trade si le seuil de survie est franchi.
54. En tant que Quentin, je veux s borné de 30 % à 50 %, départ 40 %, afin que le plancher glissant reste dans la plage tranchée.
55. En tant que Quentin, je veux une notification quand le seuil de survie est franchi, et plus aucun ordre de la méthode sortante, afin d'être prévenu sans arrêt global du système.
56. En tant qu'évaluateur, je veux accumuler le rapport de vraisemblance dès le premier trade et ne lire la décision qu'à partir du trade 30, afin de respecter le SPRT en t séquentiel.
57. En tant qu'évaluateur, je veux émettre `METHOD_CHANGE_REQUIRED` si la borne basse est franchie, afin d'abandonner une méthode sans avantage.
58. En tant qu'évaluateur, je veux émettre `METHOD_VALIDATED` si la borne haute est franchie, afin de garder une méthode qui a démontré un avantage, sans la changer pour ce motif.
59. En tant qu'évaluateur, je veux figer les bornes et l'effet minimal à l'activation de la méthode, afin que les règles statistiques ne bougent pas après la première donnée.
60. En tant qu'évaluateur, je veux calibrer l'effet minimal par Monte-Carlo pour que le nombre moyen de trades avant décision reste au plus 300, afin de tenir l'horizon tranché.
61. En tant qu'évaluateur, je veux émettre `METHOD_CHANGE_REQUIRED` sur un drawdown de méthode dès le premier trade, afin de ne pas attendre le verrou de 30 trades pour couper une perte.
62. En tant que Quentin, je veux le drawdown borné de 15 % à 25 %, départ 20 %, afin de rester dans la plage tranchée.
63. En tant qu'évaluateur, je veux, à 300 trades sans borne franchie, n'émettre aucun verdict statistique et quand même demander un changement de méthode, afin de ne pas garder un avantage non démontré.
64. En tant qu'évaluateur, je veux un arrêt dur seulement quand le capital ne permet plus un ordre à la taille minimale qui respecte le plafond de risque, afin de ne pas arrêter le système avant que le capital soit perdu.
65. En tant que Quentin, je veux que la fraction de mise soit bornée de 10 % à 25 %, départ 17,5 % hors bootstrap et 10 % en bootstrap, afin que la valeur courante soit clampée dans les bornes.
66. En tant que Quentin, je veux que la couche méta future ne puisse écrire qu'une valeur courante, ramenée dans des bornes immuables au runtime, afin que les plafonds de risque ne soient pas desserrés à chaud.
67. En tant que Quentin, je veux recevoir les événements par mail, canal par défaut, afin d'être prévenu sans dashboard.
68. En tant que Quentin, je veux que l'image du garde-fou n'importe ni LLM ni LangGraph, afin que le chemin de décision reste du code pur.
69. En tant que Quentin, je veux mypy strict en CI, afin qu'un typage faible ne laisse passer un flottant ou un contrat cassé.
70. En tant que Quentin, je veux que le mode à blanc exécute les mêmes règles et le même dimensionnement que le mode réel, afin que la validation à blanc soit celle qui protégera l'ordre réel.
71. En tant que Quentin, je veux quitter le mode à blanc seulement par un acte explicite de ma part, afin que le défaut reste sans envoi.
72. En tant que Quentin, je veux que le niveau 3, ordre BTC-EUR réel à la taille minimale, stop natif, registre reconstruit, soit bloqué derrière mon STOP, afin qu'aucun agent ne l'exécute dans ce lot.
73. En tant que CI, je veux les niveaux 1, 1 bis, 1 ter et 2 verts sans réseau et sans LLM, afin de merger sans toucher au courtier.
74. En tant que Quentin, je veux que l'API interne soit joignable en local avec le jeton, afin de tester le garde-fou sans attendre l'hébergement.
75. En tant que Quentin, je veux que l'exposition prévue derrière Cloudflare Tunnel et Access ne bloque pas L0, afin que l'hébergement, encore non tranché, ne retarde pas la mécanique.

## Implementation Decisions

- Un seul conteneur garde-fou contient les six modules. Lui seul détient la clé et le réseau sortant vers Revolut X. Les appelants ne parlent qu'à l'API HTTP interne.
- L'API authentifie chaque appel par jeton. Un appel sans jeton valide est rejeté avant toute règle de trading.
- L'entrée d'ordre est une intention : identifiant de méthode, paire, côté, prix de stop, annotation. Pas de quantité. La sortie est une acceptation ou un refus avec un code. La première règle violée gagne, dans l'ordre R0 à R8, et n'appelle pas le courtier.
- Le mode à blanc est un paramètre, activé par défaut. Il exécute la validation et le dimensionnement. Il n'envoie ni ordre, ni stop, ni vente de filet. Les lectures courtier ne sont faites que si l'ADR les confirme. Si une donnée exigée par une règle manque, la règle refuse, fail-closed.
- Le passage hors mode à blanc est un acte explicite de Quentin. Le premier ordre réel n'est pas dans le travail délégué de cette spec.
- Le courtier est derrière un port. L'adaptateur n'est écrit qu'après l'ADR issue de la documentation officielle courante. L'ADR couvre le stop natif, la taille minimale, le pas de quantité, les droits de la clé, les limites de débit et la restriction par IP. Un écart avec le cahier 1 stoppe le code concerné et remonte la question. Aucune forme d'endpoint n'est devinée dans cette spec.
- La quantité suit la formule du cahier 1 : risque sur la distance au stop plus les frais des deux côtés, plafonné par la fraction de mise. Décimaux uniquement. Arrondi à l'inférieur au pas. Sous le minimum : refus `BELOW_MIN_SIZE`. Le taux de frais taker est lu à l'API, pas codé en dur. Le glissement du stop n'entre pas dans cette formule.
- Bootstrap sous 30 trades de la méthode active : risque 1 %, mise 10 %. À partir de 30 trades : risque = min(1 %, demi-Kelly empirique) sur les multiples R nets depuis l'activation. Kelly négatif ou nul : `METHOD_CHANGE_REQUIRED`. La variante de Kelly sous contrainte de drawdown est hors L0.
- Le filet est un processus séparé dans le même conteneur, boucle configurable, départ 5 secondes, sous les limites de débit de l'ADR. Identifiant client dérivé de la position. L'historique d'exécution est relu avant toute vente. Vente spot sur solde insuffisant : position déjà clôturée. Courtier injoignable : notification et blocage des nouveaux ordres.
- Le registre est reconstruit depuis le courtier. L'API interne génère l'identifiant client, le transmet au courtier, et range l'annotation sous ce même identifiant. Stockage SQLite append-only. Un trade est un aller-retour complet. Les exécutions partielles d'un ordre sont un seul remplissage au prix moyen pondéré par la quantité. Seul un trade fermé alimente le PnL, le compteur et le SPRT. Toute divergence émet `LEDGER_ANOMALY`.
- L'évaluateur émet `METHOD_CHANGE_REQUIRED`, `METHOD_VALIDATED`, ou rien. Survie dès le trade 1 : capital ≤ (1 − s) × capital maximal atteint, s de 30 % à 50 %, départ 40 %. Drawdown dès le trade 1, d de 15 % à 25 %, départ 20 %. SPRT en t séquentiel, variance inconnue : le rapport de vraisemblance s'accumule dès le trade 1, la décision se lit au trade 30. Borne haute ln 16, borne basse ln(0,20 / 0,95). Hypothèse nulle : moyenne nulle. Hypothèse alternative : moyenne = effet minimal × écart-type. L'effet minimal est calibré par Monte-Carlo pour un nombre moyen de trades avant décision ≤ 300, puis figé à l'activation. À 300 trades sans borne : pas de verdict statistique, changement de méthode quand même. Arrêt dur : plus d'ordre minimal possible sous le plafond de risque. Conséquence d'un seuil de survie : changement forcé, notification, plus aucun ordre de la méthode sortante. Pas d'arrêt global.
- Configuration versionnée. Bornes immuables au runtime. Valeur courante clampée dans les bornes. Plafond de mise 10 % à 25 %, départ 17,5 % et 10 % en bootstrap. Plafond d'exposition 25 % à 50 %, départ 25 %. Risque max par ordre 1 %, non affiné. Spread max 0,2 %, non affiné. Les taux d'erreur du SPRT, 5 % et 20 %, ne sont pas affinés.
- Notifications par mail, canal par défaut. Liste décidée dans l'ADR 0002 : `METHOD_CHANGE_REQUIRED`, `HARD_STOP`, `SAFETY_NET_FIRED`, `BROKER_UNREACHABLE`, `LEDGER_ANOMALY`, `METHOD_VALIDATED`. Le stop natif n'est pas posé : `STOP_POLICY` est `refuse_naked`.
- Cloudflare Tunnel et Access sont la forme d'exposition prévue, pas un hébergement choisi. L0 livre l'API locale authentifiée. L'hébergement reste ouvert.
- Aucune dépendance LLM ni LangGraph dans l'image du garde-fou. Python. mypy strict en CI.
- La vérification des droits de la clé dépend de ce que l'API expose. La méthode précise reste vide tant que l'ADR ne la donne pas. Le démarrage du chemin « ordre réel » échoue tant que cette vérification n'est pas consignée. Le mode à blanc n'a pas besoin de la clé pour refuser une intention dont les entrées sont fournies. Il en a besoin si une règle exige une lecture courtier.

## Testing Decisions

Un bon test observe le comportement externe : code de refus, quantité, événement, ligne de registre, appel courtier effectué ou non. Il ne vérifie pas l'intérieur des fonctions privées.

Deux coutures, déjà acceptées. La plus haute est l'API HTTP du garde-fou branchée sur un faux serveur Revolut X qui reproduit le contrat consigné dans l'ADR. C'est le niveau 2. Les neuf scénarios du cahier 1 passent par cette couture : stop annulé, stop exécuté juste avant le tick, échec de pose du stop, timeout ou 5xx, ordre sans annotation et l'inverse, exécution partielle, spread au-dessus de 0,2 %, seuil de survie, logs sans clé. Le mode à blanc est testé sur cette même couture : mêmes refus, zéro écriture courtier.

La couture basse couvre les contrats publics des modules de validation, de dimensionnement et d'évaluation, parce que le cahier 1 exige ces cas en niveau 1. Chaque règle R0 à R8 en acceptation et en refus. La formule de quantité. Le rapport de vraisemblance et les bornes. Le drawdown. Le clamp des bornes. Des tests de propriétés : pour toute entrée, perte au stop ≤ 1 % du capital et mise ≤ fraction de mise. Un Monte-Carlo du SPRT : sous les deux hypothèses, les taux d'erreur observés sont proches de 5 % et de 20 %.

Les niveaux 1, 1 bis, 1 ter et 2 tournent en CI sans réseau et sans LLM. Le niveau 3 n'est pas un test automatisé de cette spec.

Il n'y a pas de tests antérieurs dans le dépôt. Le faux serveur est le premier de son genre. Son contrat suit l'ADR, pas une mémoire de l'API.

## Out of Scope

- Lots L1 à L7 : contrats versionnés, automate, LangGraph, backtest pré-filtre, prompts, routage Jev et LiteLLM, Langfuse, couche méta, exploitation.
- Tout agent LLM, tout appel de modèle, tout dashboard.
- Kelly sous contrainte de drawdown.
- Choisir l'hébergement, déployer, ouvrir le tunnel Cloudflare, envoyer le premier ordre réel.
- Redéployer pendant une position ouverte.
- Modifier un invariant I1 à I9 ou S1 à S10.
- Inventer une valeur encore à trancher, y compris la liste exacte des mails et la méthode de vérification des droits de clé tant que l'ADR ne les a pas levées.
- Deviner les endpoints Revolut X.

## Further Notes

Les cahiers priment sur `CLAUDE.md`. La liste de mails et le stop natif sont décidés dans l'ADR 0002. Les écarts 2 à 6 sont décidés dans l'ADR 0003.

Q1 à Q6 du cahier 1 sont tranchés et repris ci-dessus. Q7 à Q14 sont des défauts configurables, pas des trous. Q13 place l'automate en L2. Q14 retient Python, SQLite, les tests de propriétés, le secret Docker, l'isolation réseau, les décimaux, mypy strict, et zéro dépendance LLM dans le garde-fou.

Le dépôt local n'a pas encore de commit. Cette issue est la spec. Elle ne déclenche ni push, ni ordre, ni déploiement.
