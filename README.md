# Couvert ou pas

Un sinistre, des conditions générales, un verdict qui cite ses clauses et qui sait dire qu'il ne sait pas.

Application : https://couvert.mareeastforge.com (accès réservé, un code à usage unique est envoyé à l'adresse autorisée).
Réalisé en novembre 2026 pour l'exercice de recrutement IA du Groupe Foyer, sujet 1. Auteur : Hamza Chebbi, AI & Full-Stack Software Engineer.

## Ce que ça fait

Vous choisissez un contrat d'assurance habitation du marché luxembourgeois, vous décrivez un sinistre en une ou deux phrases, et le système répond couvert, non couvert, ambigu ou information insuffisante. Chaque verdict s'appuie sur des clauses citées avec la page et le passage exact. Quand une information manque pour trancher, il pose la question au lieu de deviner. Quand le contrat se lit de deux façons, il montre les deux lectures.

À côté du verdict, le système affiche ce qu'il a compris du contrat : les familles de garanties présentes, les conditions du vol, les plafonds, les franchises, les exclusions notables, chaque valeur reliée à sa page.

## Pourquoi pas un chatbot sur le PDF

Injecter le contrat entier dans un modèle marche sur un contrat et s'écroule ensuite : la clause utile se perd au milieu de cent pages, rien n'est cité, et un deuxième contrat demande tout à refaire. Ici, le contrat est d'abord transformé en tables : une ligne par clause avec sa page, une ligne par rangée de tableau avec ses en-têtes, une ligne structurée par contrat. Le modèle n'est appelé qu'après, sur les clauses retenues.

## Comment ça marche

Quatre briques et un dispatcher.

1. Parsing, payé une fois par contrat. Chaque ligne du PDF est lue avec sa page, sa police et sa graisse, et le plan des articles est reconstruit par un profil de mise en page d'une dizaine de lignes par assureur. Chaque clause reçoit un identifiant, ses pages et ses familles de garanties. Docling lit les tableaux, et chaque rangée devient une unité de recherche qui emporte ses en-têtes. Une ligne structurée par contrat est extraite avec une citation par valeur.
2. Lecture de la question. La question devient des champs typés : événement, objet, lieu, circonstances, faits donnés. Des règles, pas le modèle, listent les faits que l'événement exige en général, par exemple effraction et antivol pour un vol. Chaque fait est marqué donné, absent ou sans objet.
3. Recherche, filtre d'abord. Les clauses sont filtrées par contrat et par famille de garantie, puis cherchées par mots-clés (BM25 avec racinisation française) et par embeddings, fusionnées par rang réciproque, et reclassées par un arbitre qui note chaque finaliste de 0 à 3 en un seul appel. Les définitions de l'événement et les exclusions générales sont toujours ajoutées, déclarées et non découvertes.
4. Verdict typé. Un seul appel au modèle renvoie un objet structuré : verdict, raisonnement, clauses citées, faits manquants, plafond, franchise, confiance. Le code vérifie ensuite que chaque citation est un extrait exact de la clause, retire celles qui ne le sont pas, et rétrograde tout verdict assuré qui repose sur un fait absent de la question.

Le modèle économique sert à la lecture de la question, au reclassement et à l'extraction de la ligne structurée. Le modèle fort ne sert qu'au verdict. Les réponses sont mises en cache, les questions du jeu annoté sont précalculées, et un plafond quotidien borne les questions nouvelles.

## Les contrats

| Contrat | Édition | Pages | Source |
|---|---|---|---|
| AXA Luxembourg, OptiHome | Octobre 2025 | 118 | [axa.lu](https://axa.lu/sites/axa/files/2025-10/CA_OptiHome_W03_24_FR_1.pdf) |
| Baloise Luxembourg, HOME | CG-HOME(2)-LUFR-09-24 | 48 | [baloise.lu](https://www.baloise.lu/dam/baloise-lu/1890/particulier/documents/CG-CS/CG-HOME-2--LUFR-09-24.pdf) |
| Lalux, easyPROTECT | Mai 2017 | 117 | [lalux.lu](https://www.lalux.lu/fileadmin/mediatheque/terms_and_conditions/X9C/fra_dg_easypropart_052017_fr-v2.pdf) |

Les conditions easyPROTECT couvrent plusieurs branches, seules les parties habitation, les conditions administratives et les définitions sont ingérées. Les conditions générales Mozaïk de Foyer ne sont servies qu'après saisie d'un numéro de client et de contrat, elles ne sont donc pas publiques et n'ont pas été utilisées. Les PDF ne sont pas versionnés, `scripts/fetch_sources.py` les retélécharge et vérifie leur empreinte.

## Évaluation

À COMPLÉTER APRÈS LA PREMIÈRE ÉVALUATION : nombre de questions, exactitude par classe, taux de citation correcte, faux « couvert » et faux « non couvert » comptés séparément, taux d'abstention et abstentions justifiées. Les mêmes chiffres sont dans l'onglet Évaluation de l'application, calculés par `scripts/evaluate.py` depuis `data/eval/results.json`.

Ce qui a échoué en route, et ce qui a été changé : À COMPLÉTER.

## Des centaines de contrats

La ligne structurée par contrat est la réponse. Elle contient six à dix champs qu'un gestionnaire nomme sans réfléchir : assureur, produit, édition, familles de garanties, conditions du vol, plafonds, franchises, exclusions notables. Avec trois cents contrats, cette table se remplit une fois à l'ingestion, et chaque question commence par un filtre dessus avant toute recherche dans le texte. Le coût par question cesse de suivre la taille du corpus. Les questions qui reviennent souvent, par exemple « quels contrats excluent la chaleur sans incendie », deviennent une colonne de plus, remplie une fois et citée.

Le deuxième levier est le profil de mise en page. Un assureur compose ses conditions toujours de la même façon, et dix lignes de règles sur la police, le corps et la graisse suffisent à retrouver son plan. Un nouvel assureur demande un nouveau profil, pas un nouveau modèle.

## Limites

Trois contrats et vingt-cinq questions, pas un produit. Pas de conditions particulières, donc pas de capitaux assurés ni d'options souscrites. Le plan des articles est reconstruit par heuristiques et peut se tromper sur une mise en page inédite. La confiance est une estimation, pas une probabilité calibrée. Aucune donnée personnelle n'est stockée, les questions posées sont conservées en cache sans identifiant.

## Ce que ça a donné en production

Ce prototype reprend des choix que j'ai faits sur une plateforme en production depuis deux ans chez un client au Canada : onze agents d'extraction documentaire, un RAG hybride sur pgvector, un score de confiance et la source derrière chaque valeur, et une réponse « information insuffisante » à la place d'une supposition plausible. Deux choses m'ont marqué. La première : le client demandait plus de couverture d'automatisation, et la vraie contrainte était la confiance de ses opérateurs, qui revérifiaient tout. Afficher la source et admettre l'incertitude a fait baisser la couverture mesurée et monter l'usage réel. La seconde : un changement de prompt a dégradé la qualité pendant des semaines sans qu'aucun health check ne bouge, et c'est pour cela que l'évaluation sur jeu annoté conditionne chaque release depuis. L'onglet Évaluation de ce prototype est la version miniature de ce garde-fou.

## Sujet 2, un RAG sur un fichier Excel de cent mille lignes

Un fichier de cent mille lignes n'est pas un corpus de texte, c'est une table. La première décision est de ne pas le traiter comme un document. Je commence par profiler les colonnes : types, cardinalités, taux de remplissage, et je demande à la personne qui utilise ce fichier sur quoi elle filtre. Les colonnes qu'elle nomme sans hésiter sont les vraies colonnes. Le fichier est chargé tel quel dans une base interrogeable, SQLite, DuckDB ou PostgreSQL, avec les types corrigés et une clé de ligne.

Ensuite, les questions sont routées selon leur forme. Une question d'agrégation ou de filtre, « combien de sinistres vol en 2025 dans le canton d'Esch », devient une requête SQL générée par le modèle à partir du schéma et de quelques valeurs d'exemple, exécutée, et dont le résultat est cité avec la requête. Une question de recherche sur une colonne de texte libre, « les dossiers où le client mentionne une fuite du voisin », passe par une recherche hybride, mots-clés et embeddings, sur ces colonnes seulement, chaque ligne sérialisée avec ses en-têtes pour que la ligne retrouvée se lise comme une phrase. Une question mixte filtre d'abord en SQL, puis cherche dans les lignes restantes. Dans tous les cas, la réponse cite les identifiants de lignes, jamais un résumé flottant.

Ce qu'il ne faut pas faire : découper le fichier en morceaux de mille lignes et les vectoriser, parce qu'aucune question ne porte sur un morceau de mille lignes, et que les chiffres sortis d'un modèle qui lit un bloc sont faux une fois sur dix. L'évaluation est un jeu de trente questions avec leur réponse calculée à la main, les erreurs de routage comptées à part des erreurs de SQL.

## Sujet 4, classification des demandes entrantes

Je commence par la liste des services et de ce que chacun traite, écrite avec eux, pas déduite des mails. C'est la taxonomie, dix à vingt classes, avec les cas limites nommés dès le départ : un mail qui concerne deux services, une pièce jointe sans texte, un client qui répond à un ancien fil.

Chaque demande entrante devient un objet typé avant toute décision : expéditeur, canal, type de document, numéro de contrat ou de sinistre s'il apparaît, produit, urgence, pièces jointes et leur type, langue. Une partie de ces champs se remplit par règles, par exemple un numéro de police dans l'objet, et c'est la partie la plus fiable. Le reste est rempli par un modèle avec un schéma de sortie et une confiance.

La décision est à trois niveaux. Au-dessus d'un seuil, routage automatique vers le service, avec la raison affichée. Entre deux seuils, proposition au gestionnaire qui valide en un clic. En dessous, file d'attente humaine. Les seuils sont fixés sur un jeu annoté par les services, classe par classe, parce qu'une erreur de routage vers le juridique ne coûte pas la même chose qu'une erreur vers le marketing. Chaque correction humaine est conservée et devient le jeu d'évaluation du mois suivant, et un tableau par classe montre le volume, la précision et le taux d'escalade. Un changement de taxonomie ou de prompt ne passe en production que s'il ne dégrade aucune classe sur ce jeu.

## Lancer en local

```
git clone https://github.com/hamzachebbigit/couvert-ou-pas
cd couvert-ou-pas
python -m venv .venv && .venv/Scripts/activate      # ou source .venv/bin/activate
pip install -e .
cp .env.example .env                                # renseigner GEMINI_API_KEY et les identifiants de modèles
uvicorn app.main:app --port 7860
```

Les clauses parsées, l'index et le jeu annoté sont versionnés, l'application répond donc dès le clone pour les questions déjà analysées. Pour tout refaire depuis les PDF :

```
pip install -e .[ingest]
python scripts/fetch_sources.py
python scripts/ingest.py --all
python scripts/build_index.py
python scripts/extract_rows.py
python scripts/warm_cache.py
python scripts/evaluate.py
```

Les tests : `pip install -e .[dev]` puis `pytest`. L'image Docker : `docker build -t couvert-ou-pas .` puis `docker run -p 7860:7860 --env-file .env couvert-ou-pas`.

## Structure

```
app/main.py                 l'API et la page
app/security.py             vérification du jeton Cloudflare Access
app/pipeline/parse.py       PDF → lignes → plan → clauses, rangées de tableau
app/pipeline/profiles.py    les règles de mise en page par assureur
app/pipeline/families.py    familles de garanties et faits exigés par événement
app/pipeline/question.py    lecture typée de la question
app/pipeline/index.py       BM25 et embeddings
app/pipeline/retrieve.py    filtre, hybride, fusion, arbitre
app/pipeline/verdict.py     verdict typé et vérifications de code
app/pipeline/extract.py     la ligne structurée par contrat
app/pipeline/providers.py   fournisseurs de modèles et repli
prompts/                    les prompts, versionnés
data/parsed/<contrat>/      clauses.json, table_rows.json, row.json
data/eval/                  questions.jsonl annoté à la main, results.json
```
