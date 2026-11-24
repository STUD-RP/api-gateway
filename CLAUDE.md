# CLAUDE.md — STUD'RP : contrats d'API + API Gateway (équipe 6)

Consignes pour les agents de code (Claude Code, Codex, Cursor…) et pour les humains de
l'équipe. Elles valent pour toutes les tâches. Les consignes propres à une tâche sont
données dans la demande. **Le contrat OpenAPI fait foi** : si ce fichier le contredit,
c'est le contrat qui gagne, et il faut signaler l'écart.

---

## 1. Commandes (à connaître en premier)

| Où | Besoin | Commande |
|---|---|---|
| racine | Vérifier les contrats hors ligne | `npm run check` (voir note Windows ci-dessous) |
| racine | Linter les contrats (Spectral) | `npm run lint` |
| racine | Assembler les contrats (refs résolues) → `dist/` | `npm run bundle` |
| racine | Mock d'un service (Prism, ports 4011–4015) | `npm run mock:stud` … `npm run mock:money` |
| `gateway/` | Installer (reproductible) | `npm ci` |
| `gateway/` | Démarrer en dev / en prod | `npm run dev` / `npm start` |
| `gateway/` | Tests | `npm test` (`node --test`) |
| `gateway/` | Lint | `npm run lint` |

**Note Windows** : `npm run check` appelle `python3`, qui ouvre le Microsoft Store sur
certains postes. Utiliser `python -I tools/check_contracts.py contracts`, après
`python -m pip install pyyaml jsonschema attrs`.

**Définition de « terminé »** pour une tâche qui change le comportement :
`npm test` vert dans `gateway/`, `npm run check` et `npm run lint` verts à la racine,
et aucun secret dans le diff.

---

## 2. Vue d'ensemble du projet

TP CNAM « ERP d'une association étudiante ». Association cliente de référence :
**CNAMUS**. Une seconde, **ADECAWEB**, sert à prouver le multi-association.
Nous sommes l'**équipe 6 (Architecture)**. Nous livrons :

1. les **contrats OpenAPI 3.1** des 5 services et de la gateway (ce dépôt) ;
2. l'**API Gateway** REST (`gateway/`, à créer), seul point d'entrée entre clients et
   services. Elle s'occupe du routage, de l'authentification, du bus d'événements, de la
   santé des services et de la documentation.

| Service | Rôle | Port local | Mock Prism |
|---|---|---|---|
| STUD | Étudiants, adhésions, soldes, alumni | 3001 | 4011 |
| ASSO BACK | Catalogue, événements, stock, comptabilité | 3002 | 4012 |
| ASSO RMS | Caisse mobile, ventes | 3003 | 4013 |
| STUD'RP ADMIN | Associations, banque, commissions, tickets | 3004 | 4014 |
| STUD'RP MONEY | Paiements SumUp, partage association / plateforme | 3005 | 4015 |
| **GATEWAY** | Routage, auth, bus d'événements, doc | **8080** | — |

Chaque service a **sa propre base**. Il n'y a aucune base partagée : les données
circulent uniquement par l'API et par les événements.

### Arborescence réelle

```
.
├── CLAUDE.md                 ← ce fichier
├── README.md                 ← conventions des contrats (à lire)
├── package.json              ← scripts check / lint / bundle / mock
├── subscriptions.yaml        ← qui émet / qui reçoit chaque événement (lu par la gateway)
├── contracts/
│   ├── gateway.openapi.yaml  ← LE contrat à implémenter (+ 18 événements en `webhooks`)
│   ├── stud|back|rms|admin|money.openapi.yaml
│   └── common/schemas.yaml, common/events.yaml
├── tools/check_contracts.py
└── gateway/                  ← code de la gateway (à créer)
    ├── src/app.js            ← fabrique buildApp(config), testable via inject()
    ├── src/server.js         ← lecture de la config + listen + arrêt propre
    ├── src/config.js         ← lecture et validation des variables d'env.
    ├── src/plugins/          ← un plugin Fastify par domaine (auth, proxy, events, health, docs)
    └── test/
```

Les contrats sont **à la racine** de ce dépôt, et non dans `studrp-contracts/` comme
l'indique l'ancienne passation. Depuis `gateway/`, on a donc `CONTRACTS_DIR=..`.
Le `README.md` mentionne un `.spectral.yaml`, mais il n'est pas dans le dépôt :
**le signaler** plutôt que d'en inventer un.

### Stack

- **Node.js ≥ 22 LTS** (poste actuel : 22.17), **Fastify**, modules **ESM**, JavaScript annoté en JSDoc.
- Plugins : `@fastify/http-proxy` (routage), `@fastify/jwt`, `@fastify/rate-limit`,
  `@fastify/cors`, `@scalar/fastify-api-reference` (`/docs`).
- Validation : **Ajv 2020-12** (`ajv/dist/2020` + `ajv-formats`). Ne jamais utiliser
  l'import `ajv` par défaut, qui est en draft-07 et ignore en silence des mots-clés 2020-12.
- `$ref` entre fichiers : `@apidevtools/json-schema-ref-parser` ou les bundles `dist/`.
- Journal d'événements : **SQLite** (`node:sqlite`, sinon `better-sqlite3`).
- Logs : pino (intégré à Fastify). Tests : `node:test` + `app.inject()`.

Toute autre dépendance **doit être validée par l'utilisateur** avant son ajout (§7).

---

## 3. Architecture et règles de conception

- **Aucune logique métier dans la gateway.** Pas de calcul de prix, de solde ni
  d'écriture comptable. La gateway route, authentifie, trace et distribue.
- **Une fabrique `buildApp(config)`** sans effet de bord. `server.js` est le seul fichier
  qui lit `process.env` et qui appelle `listen()`. Les tests construisent une app neuve
  par test et la ferment (`t.after(() => app.close())`).
- **Un plugin par domaine**, dans `src/plugins/`. Les plugins partagés (config, auth,
  base d'événements) passent par `fastify-plugin` pour casser volontairement
  l'encapsulation. Les autres restent encapsulés.
- **Config validée au démarrage.** Si une variable manque ou est invalide, le processus
  s'arrête avec un message clair. Il ne doit jamais démarrer avec une valeur par défaut
  silencieuse pour un secret.
- **Erreurs au format RFC 9457** (`application/problem+json`, schéma `Problem` de
  `common/schemas.yaml`) avec `requestId`. Cela vaut pour les 404 de route, 413, 429,
  422, 502 et 504. Les erreurs des services en amont sont **relayées telles quelles**.
- **Arrêt propre** : sur `SIGTERM`/`SIGINT`, `app.close()` ferme la base SQLite et laisse
  finir les livraisons en cours (hooks `onClose`).
- Le détail fonctionnel (routage, auth, bus, santé, doc) est dans `gateway.openapi.yaml`
  et sa description. Ne pas le recopier ici : le lire.

### Bus d'événements : invariants à ne jamais casser

- Garantie de livraison **au moins une fois**, sans ordre garanti. Les abonnés
  dédoublonnent sur l'`id` de l'événement.
- L'événement et ses livraisons `PENDING` sont enregistrés **dans la même transaction
  SQLite**, et la gateway répond `202` **avant** de livrer (principe de l'outbox).
- Le corps livré est **l'enveloppe exacte, octet pour octet** : on signe ce qu'on envoie,
  sans resérialiser entre la signature et l'envoi.
- Calendrier des nouvelles tentatives : 10 s, 1 min, 5 min, 30 min, 2 h, puis `FAILED`.
  Un `401` passe en `FAILED` tout de suite. L'échéance de la prochaine tentative est
  **stockée en base** pour survivre à un redémarrage. Ne pas ajouter de gigue
  (*jitter*) sans validation : le calendrier est contractuel.
- `id` déjà connu → `200 {duplicate: true}`, sans aucune nouvelle livraison.

---

## 4. Style de code

- **Code en anglais, commentaires en français.** Le sujet exige un code clair et
  commenté : chaque module commence par un commentaire d'en-tête (rôle, ce qu'il ne
  fait pas), et chaque fonction exportée a un bloc JSDoc (`@param`, `@returns`, `@throws`).
- Les commentaires expliquent le **pourquoi** et ne paraphrasent pas le code.
- ESM uniquement (`import`/`export`, `"type": "module"`), `async/await`, pas de callbacks.
- Nommage : `camelCase` pour les variables et fonctions, `PascalCase` pour les classes,
  `UPPER_SNAKE_CASE` pour les constantes et les variables d'env., `kebab-case.js` pour
  les fichiers.
- Conventions JSON des contrats : camelCase, **montants en centimes entiers** suffixés
  `Cents`, dates ISO 8601 UTC, identifiants UUID v4.
- Pas de nombre magique. Les délais, limites et calendriers sont des constantes nommées
  et commentées.

```js
// ✅ Constante nommée, commentaire qui donne la raison
/** Délais avant chaque nouvelle tentative de livraison (contrat gateway, §bus). */
export const RETRY_DELAYS_MS = [10_000, 60_000, 300_000, 1_800_000, 7_200_000];

// ❌ Valeurs en dur, commentaire qui paraphrase le code
setTimeout(retry, 10000); // attend 10000 ms
```

---

## 5. Tests

- Runner : **`node:test`** + `node:assert/strict`. Requêtes HTTP via **`app.inject()`**,
  sans ouvrir de port.
- **Tests unitaires** (rapides, sans réseau) : signature HMAC sur un vecteur connu,
  calendrier des tentatives, contrôle d'association (y compris `STUDRP_ADMIN` et les clés
  de service), nettoyage des en-têtes, validation des 18 types d'événements (un exemple
  valide par type, pris dans la section `webhooks` du contrat, plus des cas invalides).
- **Tests de contrat** : valider les réponses de `/api/auth`, `/api/events` et
  `/api/health` contre les schémas du contrat gateway **assemblé** (Ajv 2020). Tester
  aussi les réponses d'erreur : chaque statut documenté doit être atteint par au moins un test.
- **Tests d'intégration** : petits serveurs `node:http` locaux sur port `0` qui jouent
  les abonnés (vérification de la signature, pannes simulées, `401`) ou les services en
  amont (timeout → `504`, connexion refusée → `502`).
- **Temps déterministe** : les délais de tentative passent par une horloge injectable
  (`node:test` `mock.timers` ou paramètre `now()`). Aucun test ne doit dormir 10 s.
- Base de test : SQLite `:memory:` ou fichier temporaire, jamais `./data/events.sqlite`.
- Un bug corrigé arrive avec un test qui échouait avant la correction.
- Un test instable est corrigé ou supprimé. On ne le relance pas jusqu'à ce qu'il passe.

---

## 6. Sécurité

La gateway est la frontière de confiance du système. Référence : **OWASP API Security
Top 10 (2023)**, en particulier API1 (BOLA, contrôle d'association), API2
(authentification), API4 (consommation de ressources) et API8 (mauvaise configuration).

### Authentification et autorisation
- Vérifier les JWT avec un **algorithme épinglé** (`algorithms: ['HS256']`) et refuser
  `alg: none`. Vérifier `exp` (durée de vie 1 h). Le `JWT_SECRET` fait au moins 32 octets
  aléatoires et reste **détenu par la gateway seule**.
- Le contrôle d'association (`{association}` de l'URL = claim `association`, sauf
  `STUDRP_ADMIN` et les clés de service) s'applique à **chaque** requête proxifiée.
  Une nouvelle route sans ce contrôle est un défaut bloquant.
- Toute comparaison de secret (clé d'API, signature HMAC, `X-Gateway-Secret`) passe par
  `crypto.timingSafeEqual`, après vérification que les longueurs sont égales, sinon la
  fonction lève une exception. Ne jamais comparer avec `===`.
- Routes publiques : **uniquement** celles listées dans le contrat. Tout le reste exige
  un jeton ou une clé de service : on refuse par défaut.

### En-têtes et proxy
- **Supprimer** les en-têtes d'identité entrants (`X-User-Id`, `X-User-Role`,
  `X-Association`, `X-Gateway-Secret`) **avant** d'ajouter les nôtres, quelle que soit
  leur casse.
- Ne pas faire confiance à un `X-Forwarded-For` fourni par le client. Configurer
  `trustProxy` explicitement selon l'hébergement (équipe 7).
- Bloquer `/api/*/v1/webhooks/*` et `/api/*/health` depuis l'extérieur. Réserver
  `/api/*/v1/internal/*` aux clés de service.
- Fixer une limite de taille de corps (`bodyLimit`), des timeouts en amont (5 s pour le
  proxy, 2 s pour la santé) et des limites de débit (10/min/IP au login, 300/min par jeton).
- Configurer CORS par **liste blanche** (`CORS_ORIGINS`). Jamais `*` avec des identifiants.

### Webhooks sortants
- Signature = HMAC-SHA256 du **corps brut**, avec le secret de l'abonné, au format
  `sha256=<hex>`.
- Les URL de livraison viennent **uniquement de la config** (`{SERVICE}_URL`), jamais
  d'un événement ni d'une requête : cela empêche le SSRF.
- Limite connue du contrat : la signature ne couvre pas d'horodatage, donc la protection
  contre le rejeu repose sur le dédoublonnage par `id` côté abonné. Ne pas changer le
  format sans passer par l'équipe 6 (§7).

### Secrets et logs
- Les secrets ne sont jamais dans Git, dans les logs, dans les messages d'erreur ni dans
  les tests. Les tests utilisent des valeurs factices évidentes (`test-secret-…`).
- `.env` est ignoré par Git. Seul `.env.example` est commité, sans valeurs réelles. Les
  vrais secrets viennent de l'équipe 7.
- pino : aucun corps de requête dans les logs, et `redact` sur
  `req.headers.authorization`, `req.headers["x-api-key"]`,
  `req.headers["x-gateway-secret"]` et `req.headers.cookie`. Un test vérifie que la
  valeur loguée vaut `[Redacted]`.

### Dépendances (chaîne d'approvisionnement)
- Commiter `package-lock.json`. Installer avec `npm ci` dans les scripts et la CI.
- `.npmrc` du projet : `ignore-scripts=true`. Si une dépendance native en a besoin
  (`better-sqlite3`), l'autoriser au cas par cas avec `npm rebuild <pkg>`.
- Lancer `npm audit` avant chaque livraison. Relire les changements du lockfile en revue.
  Préférer des versions publiées depuis plus de quelques jours.

---

## 7. Limites : ce que l'agent ne fait pas seul

| Action | Règle | Pourquoi |
|---|---|---|
| Modifier `contracts/**`, `subscriptions.yaml` | **Interdit sans accord.** S'arrêter, décrire l'écart, proposer un correctif | Les 5 autres équipes codent contre ces fichiers |
| Ajouter une dépendance hors §2 | Demander d'abord | Taille, surface d'attaque, consigne du TP |
| Mettre de la logique métier dans la gateway | Interdit | Le métier appartient aux services |
| Commiter, pousser, ouvrir une PR | Seulement sur demande | Actions visibles par l'équipe |
| Toucher à `.env`, à des secrets, à `data/` | Interdit | Données locales et sensibles |
| Désactiver un test, un lint ou une vérification | Interdit | Masque une régression |

**Points ouverts** (commission 4,5 % ou 5 %, TVA, découvert, partage SumUp, domaines
définitifs) : si l'un d'eux touche la gateway, poser la question à l'utilisateur au
lieu de supposer.

---

## 8. Git et flux de travail

- **GitHub Flow** : `main` est toujours démontrable. Chaque changement passe par une
  branche courte (`feat/…`, `fix/…`, `docs/…`, `test/…`, `chore/…`), fusionnée par PR en
  moins d'une journée si possible. Pas de Git Flow complet (`develop`, `release/*`) : il
  est trop lourd pour un TP de 8 h.
- **Conventional Commits**, en anglais, à l'impératif, avec une portée facultative :
  ```
  feat(events): persist pending deliveries in SQLite
  fix(proxy): strip forged X-User-Id header
  test(auth): cover STUDRP_ADMIN cross-association access
  docs(contracts): document missing .spectral.yaml
  ```
  Types : `feat`, `fix`, `test`, `docs`, `refactor`, `chore`, `ci`. Un changement
  incompatible porte `!` (`feat(events)!: …`) et un pied `BREAKING CHANGE:`.
- **Un commit = une intention.** On ne mélange pas un refactor et un changement de
  comportement. Un commit par phase du plan au minimum, avec des tests verts.
- **PR petites**, relisibles en 20 minutes environ (moins de 400 lignes hors lockfile).
  Fusion en **squash** : le titre de la PR devient le commit et suit donc la même convention.
- Description de PR : **quoi**, **pourquoi**, **comment tester** (commandes exactes) et
  impact sur les contrats (« aucun » ou lien vers la discussion avec l'équipe 6).
- Avant de pousser : relire le diff, vérifier qu'il ne contient ni secret, ni `.env`, ni
  `data/`, ni `dist/`, et lancer la définition de « terminé » (§1).
- Pas de `push --force` sur `main`, ni de réécriture d'un historique partagé.

---

## 9. Compte rendu attendu en fin de tâche

À la fin d'une tâche, l'agent indique en quelques lignes :
1. ce qui a été fait (fichiers principaux) ;
2. les commandes lancées et leur résultat réel, y compris les échecs ;
3. ce qui n'a **pas** été fait ou vérifié, et pourquoi ;
4. les écarts constatés avec les contrats, à faire trancher par l'équipe 6.
