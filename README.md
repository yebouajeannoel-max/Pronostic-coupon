# Pronostic-coupon

## Mise à jour automatique des scores

Le site lit `scores.json`. GitHub Actions le met à jour chaque heure avec les scores de football-data.org.

1. Dans GitHub, ouvre **Settings > Secrets and variables > Actions**.
2. Vérifie que le secret `FOOTBALL_KEY` existe. Ne mets jamais cette clé dans le site.
3. Crée un projet Supabase. Dans **Authentication > Providers > Phone**, active la connexion par téléphone et désactive la confirmation par SMS, comme demandé. Sans vérification du numéro, le mot de passe ne pourra pas être récupéré automatiquement par SMS.
4. Ajoute les secrets `SUPABASE_URL` et `SUPABASE_ANON_KEY` depuis les réglages de ton projet Supabase. La clé `anon` est une clé publique prévue pour le navigateur ; n’ajoute jamais la clé `service_role`.
5. Dans l’onglet **Actions**, active les actions si GitHub le demande, puis lance **Mettre à jour les scores > Run workflow**.
6. La tâche actualise `scores.json` et `auth-config.js`. Si Netlify est relié à ce dépôt, ces changements peuvent déclencher la publication du site.

Le service gratuit peut ne pas couvrir tous les championnats. Un match sans correspondance exacte avec les équipes et la date restera « À vérifier ». Les pronostics premium ne sont pas modifiés par cette tâche.

## Pronostics gratuits du mois

Une deuxième tâche GitHub Actions lance `scripts/update_pronostics.py` chaque jour et met à jour `pronostics.json` avec les équipes, les heures de début à Abidjan et les matchs programmés jusqu’à la fin du mois, selon les données disponibles sur football-data.org. Elle affiche un seul pronostic gratuit par jour quand les données récentes sont suffisantes. Si le secret facultatif `ODDS_API_KEY` est configuré, les cotes 1-N-2 des bookmakers couverts par The Odds API s’affichent à côté des équipes. Sans cote disponible, le site l’indique clairement. Les cotes peuvent changer et ne sont pas forcément proposées par les sites de paris accessibles en Côte d’Ivoire.

1. Vérifie que le secret `FOOTBALL_KEY` est le même que pour les scores.
2. Crée un compte sur [The Odds API](https://the-odds-api.com/) pour obtenir une clé, puis ajoute-la dans **Settings > Secrets and variables > Actions** sous le nom `ODDS_API_KEY`. Ne mets pas cette clé dans le site.
3. Dans **Actions**, lance **Mettre à jour les pronostics gratuits > Run workflow** pour faire un premier essai.
4. La tâche affiche les équipes et les matchs restants du mois. Elle propose un seul pronostic gratuit par jour quand les résultats récents le permettent. Si la clé de cotes est absente ou si l’API ne couvre pas un match, les équipes et les horaires restent affichés, avec un avis indiquant que les cotes ne sont pas disponibles.

Le pourcentage affiché est une estimation statistique, pas une promesse ni une garantie de gain. La formule est simple et n’est pas calibrée pour prédire des résultats avec certitude. Les offres et contenus premium ne sont pas rendus publics ni générés par ce fichier.

## Comptes et packs premium

Supabase Auth garde les mots de passe côté serveur. Le site ne conserve que la session de connexion dans l’onglet du navigateur. Les comptes utilisent un numéro et un mot de passe d’au moins 8 caractères ; le numéro n’est pas vérifié.

Le bouton **Connexion / inscription** reste accessible depuis la page d’accueil et les réglages. Si Supabase n’est pas encore configuré, le site garde le mode invité et explique que la création de comptes attend la configuration. Dans **Paramètres**, « Vérifier le site » contrôle les deux fichiers JSON et signale si Supabase est configuré ; ce contrôle n’écrit pas de code et ne peut pas réparer automatiquement tous les problèmes. Les propositions et idées sont envoyées par WhatsApp seulement après confirmation de l’utilisateur.

Les nouveaux prix sont : 100 F pour 1 jour, 500 F pour 7 jours, 1 000 F pour 14 jours et 1 500 F pour 1 mois. Le bouton ouvre WhatsApp pour demander le code ; le paiement et la remise du code restent manuels.

## Vérifier les scripts

Sur un ordinateur avec Python 3.12, lance `python -m unittest discover -s tests`. Cela vérifie la lecture des réponses, le calcul statistique et le format des fichiers sans appeler l’API ni utiliser la clé secrète.