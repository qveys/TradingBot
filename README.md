# TradingBot en mode à blanc

Depuis la racine du dépôt, préparer un fichier d'environnement privé hors du dépôt. `.env.example` fournit un jeton factice pour le test local.

```sh
mkdir -p "$HOME/.config/tradingbot"
export TRADINGBOT_ENV_FILE="$HOME/.config/tradingbot/docker.env"
(umask 077 && set -C && cat .env.example > "$TRADINGBOT_ENV_FILE")
docker build -t tradingbot:paper .
docker compose up -d --build --wait
```

`TRADINGBOT_ENV_FILE` désigne le fichier passé au conteneur à l'exécution. `TRADINGBOT_API_TOKEN` y est obligatoire. Pour un usage au-delà du test, remplacer le jeton factice par une valeur aléatoire, par exemple générée avec `openssl rand -hex 32`. `TRADINGBOT_MODE` est facultatif et vaut `paper` par défaut. Toute autre valeur présente fait échouer le démarrage. `startup.start()` contrôle la liste des événements mail décidée dans l'[ADR 0002](docs/adr/0002-mails-et-stop.md) et échoue si elle est vide.

L'API écoute sur `127.0.0.1:8080` côté hôte. Exemple avec le jeton factice et une intention fictive.

```sh
curl -i http://127.0.0.1:8080/ \
  -H 'Authorization: Bearer jeton-factice' \
  -H 'Content-Type: application/json' \
  --data '{"method":"demo","pair":"BTC-EUR","side":"buy","stop_price":"100.00","annotation":"exemple"}'
```

Un jeton absent ou invalide renvoie `401`. Le contrôle de santé vérifie cette réponse en interne. Une intention incomplète avec jeton valide renvoie `400`. Une intention complète atteint la règle de fraîcheur R0 et reçoit `503` avec `STALE_DATA` faute de solde, prix et carnet frais. Ce lancement couvre l'API locale et ce refus à blanc. Le dimensionnement dépend de données de courtage absentes de cette intégration.

Le serveur ne demande aucune clé Revolut X et ne fait aucun appel courtier. Le registre, les notifications et le filet ne sont pas lancés par le conteneur.

Arrêt local avec `docker compose down`.
