# État du triage par mode — 26 octobre 2026

Où en est TriBin pour un **particulier** et pour un **professionnel**, après le skill de triage v2
([triage-skill-v2.md](triage-skill-v2.md), [audit du 25 octobre](audit-2026-10-25.md), PR gyxcit/tribin#1).
Le constat court : le mode Particulier a été travaillé, mesuré et essayé en réel ; le mode Professionnel n'a été
mesuré que sur une agence fictive et jamais essayé sur de vrais dossiers.

## 1. Côte à côte

| | Particulier | Professionnel |
|---|---|---|
| **Convention** | catégories personnelles + dossiers créés par l'utilisateur (« startup », « media »), sous-dossiers libres (3 niveaux), nom `{description}_{date}` | gabarit `{client}/{year}/{project}/{category}`, codes clients, projets, catégories versionnées, nom `{date}_{client}_{project_code}_{description}_v{version}` |
| **Prompt** | p9-perso : bloc Particulier complet, deux exemples sur trois (image sans texte, série de logos) | p8 : bloc Professionnel, un exemple sur trois (devis d'un projet) |
| **Jeu d'essai** | `sandbox-perso/`, 27 fichiers (bulletins, factures, attestations, CV, logos en série, page web, photo, capture, scan, document de 2024, dossier « startup » et « Graphisme ») | `sandbox/`, 42 fichiers, 3 clients, 6 projets, 6 catégories, 2 dossiers hors gabarit (paie, banque) |
| **Mesure (Mistral Medium)** | 96,3 % de dossiers acceptables, 1 erreur sur une image de synthèse, noms propres gardés à 100 %, aucun dossier créé en double | 95,2 % (p7 : 92,9 %), 1,5 erreur confiante par passage, 83 % des erreurs signalées |
| **Essai sur de vrais fichiers** | oui : racine personnelle de l'auteur, 31 fichiers rejoués à blanc (27 identiques à son choix) puis 29 redéposés dans l'application (28 rangés automatiquement, 1 à vérifier) | **non** : aucun dossier d'agence réel, aucune convention d'équipe réelle |
| **Apprentissage** | règles apprises et corrections utilisées en réel (8 règles), dont deux héritées de l'ancien prompt à supprimer (format du nom, `_TriBin/a_trier`) | règles d'équipe contredites et alertes testées en simulation seulement ; `contradicts_team` trop strict (audit A.2 n° 21) non corrigé |
| **Outil `lister_dossiers`** | appelé quand il faut (logos : racine puis « Graphisme ») | appelé sur les INDD sans texte ; jamais sur un vrai projet |
| **Date du nom** | 6 noms sur 31 sans date (pages web, présentations sans date) | 20 noms sur 42 sans date avant le repli sur les propriétés du document (PSD, INDD, OTF, PDF sans métadonnées restent sans date) |
| **Versions** | sans objet (aucune catégorie versionnée) | `_versions/`, seuil 85 trop bas sur les bases courtes (audit A.2 n° 20) non corrigé |
| **Ce qui manque** | sens des factures (émise ou reçue), vraie photo dans le jeu d'essai, confiance qui sature à 0,98 avec les règles apprises | tout l'essai réel, les cas complexes ci-dessous, les bugs d'intégrité du lot 1 de l'audit |

## 2. Cas complexes à analyser avant d'ouvrir le mode Professionnel

Les cas sont classés du plus proche du particulier au plus spécifique à une équipe. Chacun demande un fichier dans un
jeu d'essai, une attente dans `expected.csv` et, si l'IA se trompe, une consigne ou un signal de plus.

**Proches du particulier (un indépendant, une petite structure)**

1. **Factures dans les deux sens** : facture reçue d'un fournisseur (abonnement, hébergement, matériel) et facture
   émise à un client ; émetteur et destinataire doivent être lus, pas devinés d'après le nom. En cours dans la session
   « Factures : distinguer émises et reçues ».
2. **Chaîne commerciale** : devis → bon de commande → facture d'acompte → facture de solde → avoir, pour le même
   projet ; la nature change à chaque étape, le projet reste. Paiements échelonnés : plusieurs factures pour une seule
   prestation.
3. **Plusieurs produits ou prestations sur un document** : une facture qui couvre deux projets, un relevé qui mélange
   personnel et professionnel.
4. **Mélange des deux mondes dans une même racine** : un indépendant range ses papiers personnels et son activité au
   même endroit (le cas « startup » dans une racine Particulier en est le début) ; un document peut être personnel
   pour l'un (bulletin de paie) et professionnel pour l'autre (le comptable qui le reçoit).

**Spécifiques à une équipe**

5. **Brief, maquette, livrable, source, administratif** pour un même projet : la catégorie dépend de l'état du
   document, pas de son sujet (le point faible mesuré : `reco_strategique_FINAL.pptx` rangé en brief par p7 comme par v2).
6. **Versions et déclinaisons** : v1, v2, final, puis A3, EN, 1920×1080 ; une déclinaison n'est pas une version
   (audit n° 20).
7. **Client inconnu ou nouveau projet** : le fichier nomme un client absent de la liste, ou un projet pas encore créé ;
   l'IA doit proposer la création conforme au gabarit ou rendre la main, jamais inventer un code.
8. **Convention d'équipe partagée** : plusieurs postes avec la même convention sur un serveur, corrections
   personnelles qui contredisent l'équipe, mise à jour de la convention en cours d'analyse (audit n° 30).
9. **Documents reçus d'un client qui parlent d'un autre client** (un brief qui cite un concurrent), homonymes de
   clients (« Martin »), sous-traitants qui facturent l'agence pour un projet client.
10. **Volumes** : un NAS de plusieurs milliers de dossiers, où les candidats et l'outil `lister_dossiers` doivent
    rester courts et rapides.

## 3. Avis : prêt pour des testeurs alpha ?

**Particulier : oui, en alpha fermée.** Le cœur est aligné (une méthode, un barème, des exemples, un outil pour
regarder, une mesure reproductible) et il s'est comporté de façon stable sur de vrais fichiers : 29 fichiers rejoués,
tous aux endroits attendus, un seul laissé à vérifier. Trois conditions :

- rangement automatique **désactivé** par défaut chez les testeurs (ou seuil à 90 %) tant que la confiance sature à
  0,98 avec les règles apprises : ils doivent voir les propositions avant qu'elles ne s'appliquent ;
- supprimer les règles apprises héritées de l'ancien prompt et repartir d'une base propre ;
- corriger d'abord le lot 1 de l'audit (A.1 n° 1 à 7 : statut écrasé par une analyse, copie entre volumes, fichier
  restauré invisible, double rangement depuis l'historique) : ce sont les bugs qu'un testeur rencontre dès qu'il
  annule ou clique deux fois.

**Professionnel : pas encore.** Rien n'a tourné sur un vrai dossier d'agence, un seul exemple dans le prompt, et les
cas 5 à 9 ci-dessus ne sont couverts que par une agence fictive de 42 fichiers. Avant une alpha : un essai sur une
vraie racine professionnelle (même petite), le lot 1 de l'audit, le sens des factures, et un passage sur les versions.
