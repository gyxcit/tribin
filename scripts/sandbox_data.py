"""Données de la sandbox : agence fictive, projets, fichiers déjà rangés, fichiers à ranger et rangement attendu."""

from __future__ import annotations

CLIENTS = [
    {"code": "ACME", "name": "Acme Corporation", "aliases": ["acme", "acme corp"]},
    {"code": "BRIOC", "name": "Brioches Dupont", "aliases": ["dupont", "brioches dupont"]},
    {"code": "VELOM", "name": "Vélos Martin", "aliases": ["martin", "velos martin", "vélos martin"]},
]

# (client, année, code projet, nom projet, libellé)
PROJECTS = [
    ("ACME", "2025", "2025-018", "Salon-Equip-Auto", "Stand Acme au salon Equip Auto 2025"),
    ("ACME", "2026", "2026-042", "Campagne-Noel", "Campagne de Noël 2026 Acme"),
    ("BRIOC", "2025", "2025-031", "Packaging-Galette", "Packaging galette des rois Brioches Dupont"),
    ("BRIOC", "2026", "2026-007", "Lancement-Brioche-Bio", "Lancement de la brioche bio Dupont"),
    ("VELOM", "2025", "2025-055", "Catalogue-2026", "Catalogue produits 2026 Vélos Martin"),
    ("VELOM", "2026", "2026-063", "Site-Web", "Refonte du site web Vélos Martin"),
]

CATEGORIES = ["01_Brief", "02_Creation", "03_Execution", "04_Livrables", "05_Sources", "06_Admin"]

# Fichiers déjà rangés : code projet -> catégorie -> [(date, description, version, extension)]
ROOT_FILES: dict[str, dict[str, list[tuple[str, str, int | None, str]]]] = {
    "2025-018": {
        "01_Brief": [("2025-03-04", "Brief-Stand-Salon", None, ".pdf")],
        "02_Creation": [("2025-03-20", "Pistes-Stand", 1, ".pdf"), ("2025-03-27", "Roughs-Kakemono", 2, ".jpg")],
        "03_Execution": [("2025-04-15", "Kakemono-800x2000", 1, ".pdf")],
        "04_Livrables": [("2025-04-28", "Kakemono-HD", 3, ".pdf")],
        "05_Sources": [("2025-03-05", "Logo-Acme-Quadri", None, ".png")],
        "06_Admin": [("2025-03-10", "Devis-Stand", None, ".pdf"), ("2025-05-30", "Facture-Stand", None, ".pdf")],
    },
    "2026-042": {
        "01_Brief": [("2026-09-02", "Brief-Campagne-Noel", None, ".pdf")],
        "02_Creation": [("2026-09-18", "Pistes-Affiche-Noel", 1, ".pdf"), ("2026-09-25", "Moodboard-Noel", 1, ".jpg")],
        "03_Execution": [("2026-10-05", "Affiche-Abribus", 1, ".pdf")],
        "04_Livrables": [("2026-10-08", "Visuel-Reseaux-Sociaux", 2, ".jpg")],
        "05_Sources": [("2026-09-03", "Photo-Sapin-Banque-Images", None, ".jpg")],
        "06_Admin": [("2026-09-08", "Devis-Creation-Campagne", None, ".pdf")],
    },
    "2025-031": {
        "01_Brief": [("2025-09-01", "Brief-Packaging-Galette", None, ".pdf")],
        "02_Creation": [("2025-09-15", "Pistes-Packaging", 1, ".pdf")],
        "03_Execution": [("2025-10-10", "Etiquette-Galette", 2, ".pdf")],
        "04_Livrables": [("2025-11-03", "Packaging-Galette-BAT", 3, ".pdf")],
        "05_Sources": [("2025-09-02", "Photos-Galette-Studio", None, ".jpg")],
        "06_Admin": [("2025-09-05", "Devis-Packaging", None, ".pdf"), ("2025-12-01", "Facture-Packaging", None, ".pdf")],
    },
    "2026-007": {
        "01_Brief": [("2026-02-10", "Brief-Lancement-Bio", None, ".pdf")],
        "02_Creation": [("2026-03-02", "Pistes-Creatives-Bio", 1, ".pdf")],
        "03_Execution": [("2026-04-12", "Declinaisons-PLV", 1, ".pdf")],
        "04_Livrables": [("2026-05-20", "Affiche-Lancement-Bio", 2, ".pdf")],
        "05_Sources": [("2026-02-12", "Logo-Label-Bio", None, ".png")],
        "06_Admin": [("2026-02-15", "Devis-Lancement-Bio", None, ".pdf")],
    },
    "2025-055": {
        "01_Brief": [("2025-06-02", "Brief-Catalogue", None, ".pdf")],
        "02_Creation": [("2025-06-20", "Chemin-de-Fer-Catalogue", 1, ".pdf")],
        "03_Execution": [("2025-08-01", "Catalogue-Pages-Interieures", 2, ".pdf")],
        "04_Livrables": [("2025-09-15", "Catalogue-2026-Imprimeur", 1, ".pdf")],
        "05_Sources": [("2025-06-05", "Photos-Velos-Studio", None, ".jpg")],
        "06_Admin": [("2025-06-10", "Devis-Catalogue", None, ".pdf")],
    },
    "2026-063": {
        "01_Brief": [("2026-07-01", "Cahier-des-Charges-Site", None, ".pdf")],
        "02_Creation": [("2026-07-20", "Maquettes-Accueil", 1, ".png")],
        "03_Execution": [("2026-08-25", "Integration-Pages", 1, ".pdf")],
        "04_Livrables": [("2026-09-30", "Maquettes-Validees", 2, ".pdf")],
        "05_Sources": [("2026-07-03", "Photos-Atelier", None, ".jpg")],
        "06_Admin": [("2026-07-05", "Devis-Site-Web", None, ".pdf")],
    },
}

# Fichiers placés dans des zones exclues (ne doivent jamais être parcourus ni proposés).
EXCLUDED_FILES = [
    ("ACME/2026/2026-042_Campagne-Noel/03_Execution/_PROJET_EN_COURS/Noel_mise-en-page.indd", {"kind": "indd"}),
    ("ACME/2026/2026-042_Campagne-Noel/03_Execution/_PROJET_EN_COURS/Liens/photo_sapin.jpg",
     {"kind": "image", "lines": ["Lien InDesign"]}),
    ("VELOM/2026/2026-063_Site-Web/05_Sources/Rushes/clip_atelier_001.mp4", {"kind": "mp4"}),
]

A25 = "ACME/2025/2025-018_Salon-Equip-Auto"
A26 = "ACME/2026/2026-042_Campagne-Noel"
B25 = "BRIOC/2025/2025-031_Packaging-Galette"
B26 = "BRIOC/2026/2026-007_Lancement-Brioche-Bio"
V25 = "VELOM/2025/2025-055_Catalogue-2026"
V26 = "VELOM/2026/2026-063_Site-Web"

BRIEF_NOEL = [
    "BRIEF CRÉATIF - Campagne de Noël 2026",
    "Client : Acme Corporation",
    "Projet : 2026-042 Campagne Noël",
    "Date : 1er septembre 2026",
    "Objectif : faire connaître la gamme cadeaux Acme pendant les fêtes.",
    "Supports : affiches abribus 120x176, réseaux sociaux, teaser vidéo 15 s.",
    "Ton : chaleureux, familial, premium.",
]

# Fichiers à ranger : (nom, spec du fichier, dossier attendu, nom attendu, dossiers acceptables)
INBOX: list[tuple[str, dict, str, str, list[str]]] = [
    ("scan0042.pdf", {"kind": "pdf", "mtime": "2026-10-13", "lines": [
        "IMPRIMERIE DU CENTRE - DEVIS N° D-2026-311", "Date : 12/10/2026",
        "Client final : Acme Corporation - Campagne Noël (réf. agence 2026-042)",
        "Impression de 400 affiches abribus 120x176 quadri recto", "Papier dos bleu 115 g", "Total HT : 2 340,00 EUR"]},
     f"{A26}/06_Admin", "2026-10-12_ACME_2026-042_Devis-Impression.pdf", []),
    ("Brief_Noel_ACME.pdf", {"kind": "pdf", "mtime": "2026-09-01", "lines": BRIEF_NOEL}, f"{A26}/01_Brief", "", []),
    ("copie de Brief_Noel_ACME.pdf", {"kind": "pdf", "mtime": "2026-09-04", "lines": BRIEF_NOEL}, f"{A26}/01_Brief", "", []),
    ("Facture_F2026-118.pdf", {"kind": "pdf", "mtime": "2026-10-20", "lines": [
        "FACTURE F2026-118", "Date : 19/10/2026", "Émetteur : Studio Photo Lumière",
        "Destinataire : Agence Exemple", "Objet : prise de vue produits Acme - campagne Noël 2026 (projet 2026-042)",
        "Montant TTC : 1 800,00 EUR"]}, f"{A26}/06_Admin", "2026-10-19_ACME_2026-042_Facture-Shooting-Photo.pdf", []),
    ("budget_campagne.xlsx", {"kind": "xlsx", "mtime": "2026-09-10", "sheets": {
        "Budget Noël 2026": [["Acme Corporation - Campagne Noël 2026 (2026-042)"], ["Poste", "Montant HT"],
                             ["Création", 12000], ["Impression affiches", 2340], ["Achat média réseaux sociaux", 8000]]}},
     f"{A26}/06_Admin", "", [f"{A26}/01_Brief"]),
    ("affiche_noel_v1.psd", {"kind": "psd", "mtime": "2026-09-22", "color": "#b22222", "lines": ["ACME", "Joyeux Noël", "Piste 1"]},
     f"{A26}/02_Creation", "", []),
    ("affiche_noel_v2.psd", {"kind": "psd", "mtime": "2026-09-29", "color": "#a01c1c", "lines": ["ACME", "Joyeux Noël", "Piste 1 retouchée"]},
     f"{A26}/02_Creation", "", []),
    ("affiche_noel_final.psd", {"kind": "psd", "mtime": "2026-10-06", "color": "#8b1a1a", "lines": ["ACME", "Joyeux Noël", "Version finale"]},
     f"{A26}/03_Execution", "", [f"{A26}/04_Livrables", f"{A26}/02_Creation"]),
    ("Affiche_Noel_final.pdf", {"kind": "pdf", "mtime": "2026-10-07", "lines": [
        "ACME - Joyeux Noël", "Affiche abribus 120x176 - HD pour impression", "Fichier final validé par le client le 07/10/2026"]},
     f"{A26}/04_Livrables", "", [f"{A26}/03_Execution"]),
    ("teaser_noel.mp4", {"kind": "mp4", "mtime": "2026-10-15", "lines": ["teaser Acme Noel 15s"]},
     f"{A26}/04_Livrables", "", [f"{A26}/03_Execution"]),
    ("logo_acme_HD.png", {"kind": "image", "mtime": "2026-09-03", "color": "#003366", "size": (600, 300), "lines": ["ACME", "Corporation"]},
     f"{A26}/05_Sources", "", [f"{A25}/05_Sources"]),
    ("ACME-Sans-Bold.otf", {"kind": "otf", "mtime": "2026-09-03", "lines": ["ACME Sans Bold"]},
     f"{A26}/05_Sources", "", [f"{A25}/05_Sources"]),
    ("notes.txt", {"kind": "text", "mtime": "2025-03-03", "text":
        "Réunion avec Acme du 3 mars 2025\nSalon Equip Auto 2025 : stand de 36 m2, hall 5.\n"
        "Besoins : kakemonos, comptoir d'accueil, écran vidéo.\nBudget à confirmer. Projet agence 2025-018.\n"},
     f"{A25}/01_Brief", "", []),
    ("visuel_stand.jpg", {"kind": "image", "mtime": "2025-03-25", "color": "#004080", "lines": ["ACME", "Salon Equip Auto 2025", "Vue 3D du stand"]},
     f"{A25}/02_Creation", "", [f"{A25}/04_Livrables"]),
    ("Kakemono_Salon_BAT.pdf", {"kind": "pdf", "mtime": "2025-04-22", "lines": [
        "BON À TIRER", "Kakemono 800x2000 - Acme - Salon Equip Auto 2025", "À retourner signé par le client avant impression"]},
     f"{A25}/04_Livrables", "", [f"{A25}/03_Execution"]),
    ("contrat_cession_droits.pdf", {"kind": "pdf", "mtime": "2025-03-12", "lines": [
        "CONTRAT DE CESSION DE DROITS D'AUTEUR", "Entre Agence Exemple et Acme Corporation",
        "Objet : visuels du stand Acme pour le salon Equip Auto 2025 (projet 2025-018)", "Durée : 3 ans, territoire : France"]},
     f"{A25}/06_Admin", "", []),
    ("relance_paiement.docx", {"kind": "docx", "mtime": "2025-07-15", "title": "Relance de paiement", "lines": [
        "Acme Corporation - Service comptabilité",
        "Objet : facture 2025-0412 du 30/05/2025, stand salon Equip Auto (projet 2025-018), restant due.",
        "Merci de procéder au règlement sous 8 jours."]}, f"{A25}/06_Admin", "", []),
    ("Document1.docx", {"kind": "docx", "mtime": "2026-02-09", "title": "Brief lancement brioche bio", "lines": [
        "Brioches Dupont lance sa première brioche issue de l'agriculture biologique.",
        "Projet 2026-007 - Lancement Brioche Bio.", "Cible : familles urbaines 30-45 ans.",
        "Livrables attendus : affiche, PLV magasin, posts réseaux sociaux."]}, f"{B26}/01_Brief", "", []),
    ("Presentation_pistes_creatives.pptx", {"kind": "pptx", "mtime": "2026-03-01", "slides": [
        ("Brioches Dupont - Brioche Bio", "Pistes créatives - projet 2026-007"),
        ("Piste A : Le goût du vrai", "Photo produit en lumière naturelle"),
        ("Piste B : Né dans les champs", "Illustration champêtre")]}, f"{B26}/02_Creation", "", []),
    ("IMG_3381.jpg", {"kind": "image", "mtime": "2026-02-20", "color": "#c8a165", "camera": "Canon EOS R6", "taken": "2026-02-20",
                      "lines": ["Brioche Bio", "Brioches Dupont", "Packshot"]}, f"{B26}/05_Sources", "", []),
    ("IMG_3382.jpg", {"kind": "image", "mtime": "2026-02-20", "color": "#c49a5c", "camera": "Canon EOS R6", "taken": "2026-02-20",
                      "lines": ["Brioche Bio", "Brioches Dupont", "Packshot 2"]}, f"{B26}/05_Sources", "", []),
    ("Scan_20261003.pdf", {"kind": "scan", "mtime": "2026-10-03", "lines": [
        "FACTURE N° 2026-0187", "Agence Exemple", "Client : Brioches Dupont",
        "Projet 2026-007 Lancement Brioche Bio", "Création PLV magasin", "Total TTC : 4 560,00 EUR", "Date : 02/10/2026"]},
     f"{B26}/06_Admin", "", []),
    ("plan_media.xlsx", {"kind": "xlsx", "mtime": "2026-02-25", "sheets": {
        "Plan média": [["Brioches Dupont - Lancement brioche bio (2026-007)"], ["Support", "Semaine", "Budget"],
                       ["Instagram", "S12", 3000], ["Affichage magasin", "S13", 5000]]}},
     f"{B26}/06_Admin", "", [f"{B26}/01_Brief"]),
    ("mockup_packaging_galette_v1.png", {"kind": "image", "mtime": "2025-09-18", "color": "#e3b04b",
                                         "lines": ["Galette des Rois", "Brioches Dupont", "Maquette v1"]}, f"{B25}/02_Creation", "", []),
    ("mockup_packaging_galette_v2.png", {"kind": "image", "mtime": "2025-09-24", "color": "#e0a83e",
                                         "lines": ["Galette des Rois", "Brioches Dupont", "Maquette v2"]}, f"{B25}/02_Creation", "", []),
    ("galette_etiquette_v3.ai", {"kind": "pdf", "mtime": "2025-10-14", "lines": [
        "Étiquette Galette des Rois - Brioches Dupont", "Format 90x60 mm - fichier d'exécution", "Ingrédients, poids net 500 g"]},
     f"{B25}/03_Execution", "", []),
    ("devis_signe.pdf", {"kind": "pdf", "mtime": "2025-09-08", "lines": [
        "DEVIS N° 2025-077 - BON POUR ACCORD", "Agence Exemple pour Brioches Dupont",
        "Création du packaging galette des rois (projet 2025-031)", "Montant HT : 6 500,00 EUR", "Signé le 06/09/2025"]},
     f"{B25}/06_Admin", "", []),
    ("bilan_campagne.pptx", {"kind": "pptx", "mtime": "2026-01-20", "slides": [
        ("Brioches Dupont - Bilan galette 2025", "Projet 2025-031 Packaging Galette"),
        ("Résultats", "Ventes +18 % par rapport à 2024")]}, f"{B25}/04_Livrables", "", []),
    ("catalogue_2026_maquette.indd", {"kind": "indd", "mtime": "2025-07-28", "lines": ["Catalogue 2026 Velos Martin"]},
     f"{V25}/03_Execution", "", [f"{V25}/02_Creation"]),
    ("catalogue_2026_maquette (1).indd", {"kind": "indd", "mtime": "2025-07-28", "lines": ["Catalogue 2026 Velos Martin"]},
     f"{V25}/03_Execution", "", [f"{V25}/02_Creation"]),
    ("BC_4512.pdf", {"kind": "pdf", "mtime": "2025-06-12", "lines": [
        "BON DE COMMANDE N° 4512", "Vélos Martin SAS", "Commande : conception et mise en page du catalogue produits 2026",
        "Référence agence : 2025-055", "Montant HT : 9 800,00 EUR"]}, f"{V25}/06_Admin", "", []),
    ("liste_produits.csv", {"kind": "text", "mtime": "2025-06-04", "text":
        "reference,modele,prix\nVM-101,Martin Urban 3,749\nVM-205,Martin Gravel X,1290\nVM-310,Martin Kid 20,329\n"},
     f"{V25}/05_Sources", "", [f"{V25}/01_Brief"]),
    ("export_final_OK.jpg", {"kind": "image", "mtime": "2025-09-12", "color": "#2e7d32",
                             "lines": ["Vélos Martin", "Catalogue 2026", "Couverture"]}, f"{V25}/04_Livrables", "", [f"{V25}/03_Execution"]),
    ("compte-rendu reunion.docx", {"kind": "docx", "mtime": "2026-07-08", "title": "Compte rendu de réunion", "lines": [
        "Client : Vélos Martin - refonte du site web (projet 2026-063)", "Présents : M. Martin, Julie (cheffe de projet)",
        "Décisions : boutique en ligne, 5 pages principales, mise en ligne en novembre."]}, f"{V26}/01_Brief", "", []),
    ("Questionnaire_client.docx", {"kind": "docx", "mtime": "2026-06-28", "title": "Questionnaire de démarrage site web", "lines": [
        "Entreprise : Vélos Martin", "Objectifs du site : vendre en ligne, présenter l'atelier.",
        "Sites appréciés : ..."]}, f"{V26}/01_Brief", "", []),
    ("Planning_site_v2.xlsx", {"kind": "xlsx", "mtime": "2026-07-10", "sheets": {
        "Planning": [["Vélos Martin - site web (2026-063)"], ["Étape", "Date"], ["Maquettes", "2026-07-20"],
                     ["Intégration", "2026-08-25"], ["Mise en ligne", "2026-11-03"]]}},
     f"{V26}/01_Brief", "", [f"{V26}/06_Admin"]),
    ("reco_strategique_FINAL.pptx", {"kind": "pptx", "mtime": "2026-07-15", "slides": [
        ("Vélos Martin - Recommandation stratégique", "Refonte du site web"),
        ("Parcours d'achat", "Simplifier la commande en 3 étapes")]}, f"{V26}/04_Livrables", "", [f"{V26}/02_Creation"]),
    ("textes_site.md", {"kind": "text", "mtime": "2026-08-12", "text":
        "# Textes du site Vélos Martin\n\n## Accueil\nDepuis 1987, Vélos Martin fabrique des vélos robustes à Lyon.\n\n"
        "## Atelier\nRéparation et entretien toutes marques.\n"}, f"{V26}/03_Execution", "", [f"{V26}/02_Creation"]),
    ("banniere_web_728x90.png", {"kind": "image", "mtime": "2026-09-02", "color": "#1b5e20", "size": (728, 90),
                                 "lines": ["Velos Martin - nouvelle boutique en ligne"]}, f"{V26}/03_Execution", "", [f"{V26}/04_Livrables"]),
    ("photo_equipe_velo.jpg", {"kind": "image", "mtime": "2026-07-03", "color": "#5d4037", "camera": "Sony A7 III", "taken": "2026-07-02",
                               "lines": ["Équipe atelier", "Vélos Martin"]}, f"{V26}/05_Sources", "", []),
]
