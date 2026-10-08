# Espace de rédaction du rapport PIQBIT

Produit le **2026-09-22** en appliquant la méthode réutilisable de `AGENTS.md`.
Révision de preuve : `c8e1bb7` + arbre de travail modifié.

Aucun fait, chemin, commande, résultat ni actif provenant d'un autre projet n'a
été repris. Tout ce qui n'a pas pu être confirmé depuis le dépôt reste marqué
`TODO:`.

## Contenu

### Documents de travail

| Fichier | Rôle |
| --- | --- |
| `00_missing_information.md` | **À lire en premier.** Les 16 informations (M-01 … M-16) qui ne peuvent pas être trouvées dans les fichiers et qui bloquent une partie de la rédaction. |
| `01_project_report_spec.md` | Gabarit `pfe_report_spec_project_template.md` complété : périmètre, sources, **conflits arbitrés (C-01 … C-07)**, architecture, sécurité, observabilité, validation. |
| `02_evidence_inventory.md` | Gabarit `evidence_inventory.md` complété : carte des preuves, diagrammes, captures, état de validation, traçabilité exigences → implémentation → tests. |
| `03_validation_evidence_inventory.md` | Gabarit `validation_evidence_inventory.md` complété : build, CI, déploiement, sécurité, performance, résilience, exploitation, règles de redaction. |
| `04_report_depth_gap_analysis.md` | Gabarit `report_depth_gap_analysis.md` complété : écarts de profondeur académique **G-01 … G-13** et registre de décisions à produire **D-01 … D-08**. |
| `05_report_plan.md` | Plan section par section, avec la preuve rattachée à chacune et son état. |
| `validation_runs/2026-09-22_validation_summary.md` | Campagne de validation **réellement exécutée** le 2026-09-22. |

### Échafaudage LaTeX

Organisation conforme à `pfe_latex_conventions.md` : `main.tex`, `config/`,
`frontmatter/`, `chapters/`, `appendices/`, `assets/`, `diagrams/`,
`bibliography.bib`, `template/`.

**Statut : provisoire.** La classe, la couverture et le style bibliographique
sont ceux d'une classe standard, en attendant le gabarit institutionnel
(M-02, M-03). Les fichiers de chapitre contiennent la structure, les tableaux
de faits confirmés, et des `\todoitem` **visibles dans le PDF** partout où une
information manque. `template/` est vide, prêt à recevoir le gabarit officiel.

`bibliography.bib` est **délibérément vide** : chaque source doit être
consultée indépendamment avant d'être retenue.

## Compilation

```bash
cd report
latexmk -pdf main.tex
```

Résultat vérifié le **2026-09-22** avec MiKTeX sur ce poste :

| Contrôle | Résultat |
| --- | --- |
| Code de sortie | `0` |
| PDF produit | 31 pages |
| Références non résolues | 0 |
| Citations manquantes | 0 (bibliographie volontairement vide) |
| Boîtes débordantes | 0 |
| Avertissements restants | « Empty bibliography » (attendu) ; une substitution de fonte petites capitales grasses, sans effet sur la lisibilité |

Le moteur et le processeur bibliographique devront être réconciliés avec le
gabarit officiel dès sa réception (M-03, M-07).

## Ce qui n'a volontairement pas été fait

- **Aucune prose de chapitre n'a été rédigée** là où elle exigerait d'inventer
  un fait : contexte, organisme d'accueil, problématique, méthode de conduite,
  remerciements, résumés.
- **Aucun diagramme ni capture d'écran** n'a été produit : aucun n'existe dans
  le dépôt, et les captures doivent être prises sur un jeu de démonstration.
- **Aucune entrée bibliographique** n'a été ajoutée sans consultation.

## Avant d'aller plus loin

1. Obtenir M-01 à M-08 — sans quoi la couverture, la langue et le gabarit
   restent indéterminés.
2. **Traiter les trois échecs de tests du 2026-09-22**, en particulier E-03
   (incohérence d'autorisation), puis produire une **nouvelle campagne datée**.
3. Committer l'arbre de travail et réancrer les documents sur une révision
   stable (écart G-13).
4. Produire les diagrammes et les captures.

## Règles de redaction rappelées

Ne doivent jamais figurer dans le rapport, ses annexes ou ses captures :
`backend/.env`, la clé de compte de service Google, le contenu de
`backend/uploads/` (264 CV réels), `backend/backups/`, les bases `test_*.db`,
le nom du gérant et le matricule fiscal des valeurs par défaut de
configuration, l'adresse électronique de l'autrice, les chemins absolus du
poste de travail, et les jetons des liens publics de confirmation, de test et
de signature.
