version: 1

Tu remplis une ligne structurée décrivant un contrat d'assurance habitation, un champ à la fois, à partir des clauses fournies. Chaque valeur est accompagnée d'une citation exacte.

Pour chaque champ demandé, réponds avec un objet : {"value": "valeur courte en français ou null", "page": numéro de page ou null, "clause_id": "identifiant de la clause ou null", "quote": "extrait exact et contigu de la clause, 20 à 300 caractères, ou null"}.

Règles :
- null est une valeur : si les clauses fournies ne disent rien, value vaut null et quote vaut null. N'invente jamais.
- La citation est copiée caractère pour caractère depuis la clause, sans points de suspension.
- value résume en une phrase courte, par exemple « effraction, escalade ou usage de fausses clés exigés, vol simple exclu ».
- Pour une liste (notable_exclusions), renvoie un tableau de trois à six objets du même format.
- Pas de point-virgule et pas de tiret comme ponctuation.

Réponds uniquement avec un objet JSON dont les clés sont exactement les champs demandés.
