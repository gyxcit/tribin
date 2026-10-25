"""Données du jeu d'essai Particulier : dossiers déjà rangés, fichiers à ranger et rangement attendu.

Le jeu vise les cas qui ont fait trébucher l'IA en usage réel (docs/triage-skill-v2.md) : bulletins du même modèle
de nom, factures dont une d'un projet, attestations, CV, logos en série, page web d'un projet, photo sans texte,
capture d'écran, PDF scanné, document ancien téléchargé aujourd'hui, dossier « startup » créé par l'utilisateur."""

from __future__ import annotations

from datetime import date

TODAY = date.today().isoformat()
PERSON = "Regis Likassi"

# Dossiers de premier niveau déjà présents (catégories de la convention personnelle + « startup » de l'utilisateur)
EXISTING_FOLDERS = ["Administratif", "Banque", "Impots", "Salaires", "Sante", "Logement", "Assurances", "Vehicule",
                    "Factures", "Etudes", "Famille", "Photos", "startup", "Graphisme"]


def _bulletin(month: str, label: str) -> list[str]:
    return ["BULLETIN DE PAIE", f"Période : {label}", f"Salarié : {PERSON}", "Employeur : Nova Conseil SAS",
            "Emploi : développeur", "Salaire net à payer : 2 410,15 EUR", f"Édité le {month}-28"]


# Fichiers déjà rangés : (chemin relatif, spécification)
ROOT_FILES: list[tuple[str, dict]] = [
    ("Salaires/2026_07_likassi_regis_2026_07_28T13_45_02.pdf", {"kind": "pdf", "mtime": "2026-07-28", "lines": _bulletin("2026-07", "juillet 2026")}),
    ("Salaires/2026_08_likassi_regis_2026_08_28T09_12_40.pdf", {"kind": "pdf", "mtime": "2026-08-28", "lines": _bulletin("2026-08", "août 2026")}),
    ("Banque/2026-08-31_Releve-LCL-aout.pdf", {"kind": "pdf", "mtime": "2026-09-02", "lines": [
        "LCL - Relevé de compte", f"Titulaire : {PERSON}", "Période du 01/08/2026 au 31/08/2026", "Solde : 3 120,40 EUR"]}),
    ("Factures/2026-09-16_Facture-abonnement-Free.pdf", {"kind": "pdf", "mtime": "2026-09-16", "lines": [
        "FREE - Facture n° 2026-09-7781", "Date : 16/09/2026", f"Client : {PERSON}", "Abonnement Freebox : 29,99 EUR"]}),
    ("Etudes/CV/2025-11-02_CV-Regis-Likassi.pdf", {"kind": "pdf", "mtime": "2025-11-02", "lines": [
        f"{PERSON} - Développeur", "Expérience : Nova Conseil (2024-2026)", "Formation : Master informatique, 2023"]}),
    ("Etudes/Attestations/2026-03-10_Attestation-benevolat.pdf", {"kind": "pdf", "mtime": "2026-03-10", "lines": [
        "ATTESTATION DE BÉNÉVOLAT", f"Nous attestons que {PERSON} a participé", "Association Les Restos du Cœur", "Fait le 10/03/2026"]}),
    ("Etudes/Certifications/2025-06-20_Certificat-AWS.pdf", {"kind": "pdf", "mtime": "2025-06-20", "lines": [
        "CERTIFICATE OF COMPLETION", f"{PERSON}", "AWS Cloud Practitioner", "June 20, 2025"]}),
    ("Vehicule/Entretien/2026-02-14_Facture-revision-Norauto.pdf", {"kind": "pdf", "mtime": "2026-02-14", "lines": [
        "NORAUTO - Facture", "Révision complète Peugeot 208 - AB-123-CD", "Date : 14/02/2026", "Total : 189,00 EUR"]}),
    ("Sante/2026-05-03_Ordonnance-Dr-Martin.pdf", {"kind": "pdf", "mtime": "2026-05-03", "lines": [
        "Dr Martin - Médecin généraliste", f"Patient : {PERSON}", "Ordonnance du 03/05/2026", "Doliprane 1 g"]}),
    ("Photos/2026-08-15_Plage-Biarritz.jpg", {"kind": "image", "mtime": "2026-08-15", "color": "#3a7bd5", "camera": "Apple iPhone 15",
                                             "taken": "2026-08-15", "lines": ["Biarritz", "été 2026"]}),
    ("startup/Presentation-projet-Stagio_2026-10-20.pdf", {"kind": "pdf", "mtime": "2026-10-20", "lines": [
        "STAGIO - Présentation du projet", "Plateforme de mise en relation étudiants / entreprises pour les stages",
        f"Fondateur : {PERSON}", "Octobre 2026"]}),
    ("startup/Business-plan-Stagio-v3.docx", {"kind": "docx", "mtime": "2026-10-18", "title": "Business plan Stagio", "lines": [
        "Stagio : trouver un stage en 3 clics.", "Marché : 1,2 million d'étudiants en France.", "Besoin de financement : 40 000 EUR."]}),
    # Dossier de l'utilisateur pour ses créations graphiques : l'IA doit le trouver (lister_dossiers) plutôt que créer « Design »
    ("Graphisme/Velo-Club-Lyon/Logo-Velo-Club-Lyon-v2.png", {"kind": "image", "mtime": "2026-06-12", "color": "#1b5e20", "size": (900, 900),
                                                            "lines": ["Vélo Club Lyon", "logo v2"]}),
    ("Graphisme/Affiche-fete-des-voisins.pdf", {"kind": "pdf", "mtime": "2026-05-20", "lines": [
        "FÊTE DES VOISINS - 29 mai 2026", "12 rue des Lilas", "Affiche A3, maquette finale"]}),
]

# Fichiers à ranger : (nom, spec, dossier attendu, nom attendu, dossiers acceptables, mot-clé attendu dans le nom)
INBOX: list[tuple[str, dict, str, str, list[str], str]] = [
    # Bulletins du même modèle de nom que ceux déjà rangés dans Salaires
    ("2026_09_likassi_regis_2026_09_28T10_02_11.pdf", {"kind": "pdf", "mtime": "2026-09-28", "lines": _bulletin("2026-09", "septembre 2026")},
     "Salaires", "", [], ""),
    ("2026_10_likassi_regis_2026_10_28T10_05_43.pdf", {"kind": "pdf", "mtime": TODAY, "lines": _bulletin("2026-10", "octobre 2026")},
     "Salaires", "", [], ""),
    # Factures, dont une d'un projet (abonnement pour Stagio : une facture reste une facture)
    ("Facture_Free_octobre.pdf", {"kind": "pdf", "mtime": "2026-10-16", "lines": [
        "FREE - Facture n° 2026-10-8102", "Date : 16/10/2026", f"Client : {PERSON}", "Abonnement Freebox : 29,99 EUR"]},
     "Factures", "2026-10-16_Facture-abonnement-Free.pdf", [], "Free"),
    ("invoice-OVH-1182.pdf", {"kind": "pdf", "mtime": "2026-10-03", "lines": [
        "OVHcloud - Facture FR1182", "Date : 02/10/2026", f"Client : {PERSON}", "Hébergement web stagio.fr - 12 mois", "Total TTC : 71,88 EUR"]},
     "Factures", "", ["Factures/Stagio", "startup"], "OVH"),
    ("facture_norauto_oct.pdf", {"kind": "pdf", "mtime": "2026-10-09", "lines": [
        "NORAUTO - Facture", "Changement des pneus avant Peugeot 208 - AB-123-CD", "Date : 09/10/2026", "Total : 240,00 EUR"]},
     "Vehicule/Entretien", "", ["Vehicule"], "Norauto"),
    ("Facture-EDF-2024.pdf", {"kind": "pdf", "mtime": TODAY, "lines": [
        "EDF - Facture d'électricité", "Date de la facture : 12/03/2024", f"Client : {PERSON}", "Montant TTC : 86,40 EUR"]},
     "Logement", "2024-03-12_Facture-electricite-EDF.pdf", ["Factures"], "EDF"),  # document de 2024 téléchargé aujourd'hui
    # Attestations
    ("attestation_france_travail.pdf", {"kind": "pdf", "mtime": "2026-10-21", "lines": [
        "FRANCE TRAVAIL", "Attestation d'inscription", f"{PERSON} est inscrit comme demandeur d'emploi depuis le 01/10/2026",
        "Fait le 21/10/2026"]}, "Administratif", "", ["Etudes/Attestations"], "France-Travail"),
    ("Attestation_assurance_habitation.pdf", {"kind": "pdf", "mtime": "2026-09-30", "lines": [
        "MAIF - Attestation d'assurance habitation", f"Sociétaire : {PERSON}", "Logement : 12 rue des Lilas, Lyon",
        "Valable du 01/10/2026 au 30/09/2027", "Éditée le 30/09/2026"]}, "Assurances", "", ["Logement"], "MAIF"),
    ("attestation benevolat 2026.pdf", {"kind": "pdf", "mtime": "2026-10-11", "lines": [
        "ATTESTATION DE BÉNÉVOLAT", f"Nous attestons que {PERSON} a participé à la collecte nationale",
        "Association Les Restos du Cœur", "Fait le 11/10/2026"]}, "Etudes/Attestations", "", [], ""),
    # CV
    ("CV_Regis_Likassi_2026.pdf", {"kind": "pdf", "mtime": "2026-10-19", "lines": [
        f"{PERSON} - Développeur full stack", "Expérience : Nova Conseil (2024-2026), Stagio (fondateur)",
        "Formation : Master informatique, 2023", "Mis à jour le 19/10/2026"]}, "Etudes/CV", "", [], "CV"),
    ("CV 2.pdf", {"kind": "pdf", "mtime": "2026-10-19", "lines": [
        f"{PERSON} - Développeur", "Version courte - octobre 2026", "Compétences : Python, TypeScript, AWS"]},
     "Etudes/CV", "", [], "CV"),  # « 2 » n'est pas une version
    # Trois logos d'une même série (création graphique pour une personne : ni Photos ni Etudes ; « Graphisme » existe)
    ("Planche de logos Sarah Mbossa-1.png", {"kind": "image", "mtime": "2026-10-22", "color": "#2b2d42", "size": (1200, 900),
                                             "lines": ["Sarah Mbossa", "journaliste", "logo - piste 1"]},
     "Graphisme/Sarah-Mbossa", "", ["Graphisme"], "Sarah-Mbossa"),
    ("Planche de logos Sarah Mbossa-2.png", {"kind": "image", "mtime": "2026-10-22", "color": "#8d99ae", "size": (1200, 900),
                                             "lines": ["Sarah Mbossa", "journaliste", "logo - piste 2"]},
     "Graphisme/Sarah-Mbossa", "", ["Graphisme"], "Sarah-Mbossa"),
    ("Planche de logos Sarah Mbossa-3.png", {"kind": "image", "mtime": "2026-10-22", "color": "#ef233c", "size": (1200, 900),
                                             "lines": ["Sarah Mbossa", "journaliste", "logo - piste 3"]},
     "Graphisme/Sarah-Mbossa", "", ["Graphisme"], "Sarah-Mbossa"),
    # Page web du projet Stagio : le dossier « startup » de l'utilisateur contient déjà des fichiers Stagio
    ("Stagio Traitement.html", {"kind": "text", "mtime": "2026-10-23", "text":
        "<!doctype html><html><head><title>Stagio - Traitement des candidatures</title></head><body>"
        "<h1>Stagio</h1><p>Traitement automatique des candidatures de stage : tri, relances, suivi.</p>"
        "<p>Prototype interne, octobre 2026.</p></body></html>"}, "startup", "", [], "Stagio"),
    ("Pitch Stagio investisseurs.pptx", {"kind": "pptx", "mtime": "2026-10-24", "slides": [
        ("Stagio", "Trouver un stage en 3 clics"), ("Le problème", "6 mois de recherche en moyenne"),
        ("Levée de fonds", "40 000 EUR pour 12 mois")]}, "startup", "", [], "Stagio"),
    # Photo de carte grise (image sans texte extractible), capture d'écran
    ("IMG_4820.jpg", {"kind": "image", "mtime": "2026-10-20", "color": "#c9c3b1", "camera": "Apple iPhone 15", "taken": "2026-10-20",
                      "lines": ["CERTIFICAT D'IMMATRICULATION", "AB-123-CD", "PEUGEOT 208"]},
     "Vehicule", "", ["Administratif"], ""),
    ("Capture d'écran 2026-10-24 153012.png", {"kind": "image", "mtime": "2026-10-24", "color": "#1e1e1e", "size": (1600, 900),
                                                "lines": ["Virement reçu : 1 200,00 EUR", "LCL - espace client", "24/10/2026"]},
     "Banque", "", ["Administratif"], ""),
    ("IMG_4821.jpg", {"kind": "image", "mtime": "2026-10-18", "color": "#2f6b3a", "camera": "Apple iPhone 15", "taken": "2026-10-18",
                      "lines": ["Randonnée", "Pyrénées", "octobre 2026"]}, "Photos", "", [], ""),
    # PDF scanné (aucun texte, image de la page)
    ("Scan_20261022.pdf", {"kind": "scan", "mtime": "2026-10-22", "lines": [
        "AVIS D'IMPOSITION 2026", "Impôt sur les revenus de 2025", f"{PERSON}", "Montant : 1 842 EUR", "Date : 15/09/2026"]},
     "Impots", "", ["Administratif"], ""),
    # Autres papiers courants
    ("Releve_LCL_septembre.pdf", {"kind": "pdf", "mtime": "2026-10-02", "lines": [
        "LCL - Relevé de compte", f"Titulaire : {PERSON}", "Période du 01/09/2026 au 30/09/2026", "Solde : 2 980,10 EUR"]},
     "Banque", "2026-09-30_Releve-LCL-septembre.pdf", [], "LCL"),
    ("quittance_octobre.pdf", {"kind": "pdf", "mtime": "2026-10-05", "lines": [
        "QUITTANCE DE LOYER", "Mois d'octobre 2026", f"Locataire : {PERSON}", "12 rue des Lilas, Lyon", "Loyer : 720,00 EUR"]},
     "Logement", "", [], "Quittance"),
    ("resultats_analyses.pdf", {"kind": "pdf", "mtime": "2026-10-14", "lines": [
        "LABORATOIRE BIOLYON - Résultats d'analyses", f"Patient : {PERSON}", "Prélèvement du 13/10/2026", "Glycémie : 0,92 g/L"]},
     "Sante", "", [], ""),
    ("Contrat_travail_Nova.pdf", {"kind": "pdf", "mtime": "2026-10-01", "lines": [
        "CONTRAT DE TRAVAIL À DURÉE INDÉTERMINÉE", "Entre Nova Conseil SAS et " + PERSON, "Poste : développeur",
        "Signé à Lyon le 01/10/2026"]}, "Salaires", "", ["Administratif"], "Nova"),
    ("inscription_ecole_lea.pdf", {"kind": "pdf", "mtime": "2026-09-03", "lines": [
        "ÉCOLE PRIMAIRE JEAN MOULIN", "Certificat de scolarité", "Élève : Léa Likassi, classe de CE1", "Année scolaire 2026-2027"]},
     "Famille", "", ["Administratif"], "Lea"),
    ("memoire_master_final.docx", {"kind": "docx", "mtime": "2023-06-30", "title": "Mémoire de master - Apprentissage automatique", "lines": [
        f"Auteur : {PERSON}", "Université de Lyon, 2023", "Résumé : ce mémoire étudie les réseaux de neurones appliqués au tri de documents."]},
     "Etudes", "", ["Etudes/Memoires", "Etudes/Master"], "Memoire"),
    ("Document1.docx", {"kind": "docx", "mtime": "2026-10-23", "title": "Lettre de résiliation", "lines": [
        f"{PERSON}, 12 rue des Lilas, Lyon", "À l'attention de Basic-Fit", "Objet : résiliation de mon abonnement à la salle de sport",
        "Fait à Lyon le 23/10/2026"]}, "Administratif", "", ["Factures", "Sante"], "Basic-Fit"),
]
