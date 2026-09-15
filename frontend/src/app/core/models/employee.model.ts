/** Genre — vocabulaire fermé, miroir de `app/models/employee.py`. */
export type Gender = 'F' | 'M' | 'AUTRE' | 'NON_RENSEIGNE';

export const GENDER_LABELS: Record<Gender, string> = {
  F: 'Femme',
  M: 'Homme',
  AUTRE: 'Autre',
  // Une réponse volontaire, pas un oubli : la fiche est créée par un traitement
  // automatique, et le genre ne se déduit jamais d'un prénom.
  NON_RENSEIGNE: 'Non renseigné',
};

export type EmployeeContractType = 'CDI' | 'CDD' | 'SIVP' | 'STAGE' | 'FREELANCE';

/** Libellés des champs qu'une fiche complète doit porter — pour le repère
 *  « à compléter » de la liste et du détail. */
export const EMPLOYEE_FIELD_LABELS: Record<string, string> = {
  birth_date: 'Date de naissance',
  gender: 'Genre',
  position: 'Poste',
  department: 'Service',
  contract_type: 'Type de contrat',
  hire_date: "Date d'entrée",
};

export interface Employee {
  id: string;
  firstName: string;
  lastName: string;
  email: string;
  phone: string;
  position: string;
  department: string;
  salary: number;
  hireDate: Date;
  status: 'active' | 'inactive' | 'on-leave';

  /** Date de naissance — jamais l'âge : un âge stocké vieillit mal. */
  birthDate?: string | null;
  gender?: Gender | null;
  contractType?: EmployeeContractType | null;
  educationLevel?: string | null;

  /** Calculés par l'API, en lecture seule. */
  age?: number | null;
  /** Champs restant à renseigner — vide si la fiche est complète. */
  missingFields?: string[];

  createdAt: Date;
  updatedAt: Date;
}
