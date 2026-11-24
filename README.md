# STUD'RP — Contrats d'API

Dépôt des contrats OpenAPI 3.1 de STUD'RP, maintenu par l'**équipe 6 (Architecture)**.
Le contrat fait foi : on l'écrit et on le valide **avant** de coder, et en cas de
désaccord entre un service et son contrat, c'est le service qui a tort.

La stratégie complète (propriété des données, gateway, flux, écritures comptables,
RGPD, points à valider) est dans le document « STUD'RP – Stratégie d'échange de données ».

## Contenu

```
contracts/
  gateway.openapi.yaml   Gateway : connexion, publication et journal des événements,
                         santé + catalogue des 18 événements (section `webhooks`)
  stud.openapi.yaml      STUD : étudiants, adhésions, comptes, alumni, RGPD
  back.openapi.yaml      ASSO BACK : catalogue, événements, stock, achats, comptabilité
  rms.openapi.yaml       ASSO RMS : ventes de caisse
  admin.openapi.yaml     STUD'RP ADMIN : associations, banque, commissions, tickets
  money.openapi.yaml     STUD'RP MONEY : paiements SumUp et partage
  common/schemas.yaml    Schémas, paramètres et erreurs partagés (ne pas dupliquer)
  common/events.yaml     Enveloppe d'événement et schéma de chaque type
subscriptions.yaml       Qui émet et qui reçoit chaque événement (lu par la gateway)
.spectral.yaml           Règles de lint (conventions STUD'RP)
tools/check_contracts.py Vérification hors ligne (Python + PyYAML + jsonschema)
```

## Commandes

| Besoin | Commande |
|---|---|
| Vérifier hors ligne (refs, exemples, conventions) | `npm run check` |
| Linter avec Spectral | `npm run lint` |
| Assembler un fichier par service (refs résolues) | `npm run bundle` → `dist/` |
| Simuler un service pas encore codé | `npm run mock:back` (ports 4011 à 4015) |
| Vérifier qu'un vrai service respecte son contrat | `npm run proxy:back` |

Exemple : l'équipe RMS code sa caisse contre de faux BACK et STUD dès la première heure.

```bash
npm run mock:back   # http://localhost:4012/v1/associations/cnamus/catalog/items
npm run mock:stud   # http://localhost:4011/v1/associations/cnamus/students?search=martin
```

Prism renvoie les exemples des contrats. Pour forcer un cas d'erreur, ajouter l'en-tête
`Prefer: code=422` à la requête.

## Conventions (résumé)

- URL : `/v1/associations/{association}/<ressource-au-pluriel>`, slug d'association en minuscules (`cnamus`, `adecaweb`).
- JSON en camelCase ; identifiants UUID v4 ; dates ISO 8601 UTC.
- **Montants en centimes**, entiers, suffixés `Cents` (`unitPriceCents: 50` = 0,50 €).
- Erreurs au format RFC 9457 (`application/problem+json`, schéma `Problem`).
- Listes paginées : `?page=1&pageSize=20` → `{ data: [...], pagination: {...} }`.
- `Idempotency-Key` obligatoire sur les ventes et les paiements.
- **Aucun `DELETE`** sur écritures, stock, ventes, paiements : on corrige par une écriture inverse.
- Chaque opération : `operationId`, `summary`, `description`, `tags`, et au moins un exemple.

## Ce que chaque service doit implémenter en plus de ses routes métier

1. `GET /health` → `{"status": "UP"}`.
2. `POST /v1/webhooks/events` : vérifier `X-StudRP-Signature`
   (`sha256=` + HMAC-SHA256 hexadécimal du **corps brut** avec son secret webhook),
   ignorer un `id` déjà traité, répondre `200` en moins de 5 s puis traiter.
3. Refuser toute requête sans le bon `X-Gateway-Secret`, et lire l'identité dans
   `X-User-Id`, `X-User-Role`, `X-Association` (posés par la gateway).
4. Publier ses événements avec `POST /api/events` sur la gateway (en-tête `X-Api-Key`).

## Portail de documentation

La gateway sert tous les contrats assemblés (`dist/`) sur `/docs` avec Scalar
(`@scalar/fastify-api-reference`), une entrée par service. Esquisse de configuration ;
les noms d'options sont à vérifier dans la doc Scalar de la version installée :

```js
await app.register(require('@scalar/fastify-api-reference'), {
  routePrefix: '/docs',
  configuration: {
    sources: ['gateway', 'stud', 'back', 'rms', 'admin', 'money'].map((s) => ({
      title: s.toUpperCase(),
      url: `/docs/openapi/${s}.yaml`,
    })),
  },
});
```

## Modifier un contrat

1. Ouvrir une pull request ; l'équipe 6 relit.
2. `npm run check` et `npm run lint` doivent passer.
3. Ajouter un champ est permis en `v1`. Renommer ou supprimer impose une `v2`.
4. Nouvel événement : l'ajouter dans `common/events.yaml` (enum `EventType`, schéma `*Data`
   et enveloppe typée), dans la section `webhooks` de `gateway.openapi.yaml` et dans
   `subscriptions.yaml`.

## Hypothèses à confirmer

Les contrats rendent paramétrables les points ouverts du sujet (voir le document de
stratégie, section 11) : taux de commission (4,5 % par défaut dans `AssociationSettings`),
TVA par association, découvert autorisé, faisabilité du partage en deux paiements chez SumUp.
Les domaines `*.studrp.example` sont des exemples à remplacer par ceux de l'équipe 7.
