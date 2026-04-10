# Projet : Prospection automatisée pour facture-flow.com

## Objectif business
Clément prospecte des **commerces locaux** (boutiques, artisans, PME) pour leur proposer
son logiciel de facturation **facture-flow.com**.

Le workflow permet de :
1. Chercher des commerces via Google Places (ex: "Magasin vélo Rennes")
2. Scraper automatiquement leur email + une description de leur activité
3. Créer les prospects dans le CRM Fibery
4. Clément les contacte ensuite par appel téléphonique ou email

## Structure du dossier
```
googleshop/
├── CLAUDE.md      ← ce fichier
├── workflow.py    ← script principal
└── .env           ← clés API
```

## Lancer le workflow
```bash
python workflow.py "Magasin vélo Rennes"
```

## Variables d'environnement (.env)
- `GOOGLE_PLACES_API_KEY` — Google Places API (New)
- `FIBERY_TOKEN` + `FIBERY_URL` — CRM Fibery
- `OPENROUTER_API_KEY` — LLM pour la description

## Ce que fait workflow.py
1. Appel Google Places `searchText` → jusqu'à 20 commerces avec `websiteUri`
2. Pour chaque commerce : scrape email (homepage + footer) + description IA
3. Vérifie si déjà dans Fibery (par `websiteUri`) → crée si absent et email trouvé
4. Statuts : `created` / `already_exists` / `no_email`

## Fibery CRM
- Workspace : `factureflow.fibery.io`
- Type : `Sales CRM/Account`
- Champs : `Name`, `Website`, `Email`, `Phone`, `Description`

## Notes
- Modèle OpenRouter : `meta-llama/llama-3.1-8b-instruct:free`
- Alternatives si rate-limit : `mistralai/mistral-7b-instruct:free`, `google/gemma-2-9b-it:free`
