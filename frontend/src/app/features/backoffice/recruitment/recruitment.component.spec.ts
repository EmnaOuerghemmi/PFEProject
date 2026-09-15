import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';

import { RecruitmentComponent } from './recruitment.component';
import { SemanticMatch } from '../../../core/services/semantic.service';

describe('RecruitmentComponent', () => {
  let component: RecruitmentComponent;
  let fixture: ComponentFixture<RecruitmentComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
      ],
      imports: [RecruitmentComponent]
    }).compileComponents();

    fixture = TestBed.createComponent(RecruitmentComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  // ── Regroupement par candidat ──
  //
  // La recherche par similarité travaille par CANDIDATURE : une même personne
  // qui a postulé à plusieurs offres remontait autant de fois, et la liste
  // affichait le même nom d'affilée sans dire s'il s'agissait d'un doublon.

  const match = (over: Partial<SemanticMatch>): SemanticMatch => ({
    application_id: 'a1', candidate_id: 'c1', user_id: 'u1', candidate_name: 'Alice',
    job_offer_id: 'j1', job_title: 'Dev', application_status: 'REVIEWED',
    semantic_score: 50, keyword_score: 80, skills: [], experience_years: 3,
    ...over,
  });

  const grouper = (ms: SemanticMatch[]) => (component as any).grouper(ms);

  it("réunit les candidatures d'une même personne sur une seule carte", () => {
    const groupes = grouper([
      match({ application_id: 'a1', semantic_score: 52, job_title: 'Full Stack' }),
      match({ application_id: 'a2', semantic_score: 49, job_title: 'Data Engineer' }),
      match({ application_id: 'a3', candidate_id: 'c2', candidate_name: 'Bob', semantic_score: 40 }),
    ]);

    expect(groupes.length).toBe(2);
    expect(groupes[0].candidateName).toBe('Alice');
    expect(groupes[0].applications.length).toBe(2);
    expect(groupes[1].candidateName).toBe('Bob');
  });

  it('retient la meilleure correspondance comme score du candidat', () => {
    // Le serveur renvoie déjà par correspondance décroissante : la première
    // candidature rencontrée porte donc le meilleur score de la personne.
    const groupes = grouper([
      match({ application_id: 'a1', semantic_score: 52 }),
      match({ application_id: 'a2', semantic_score: 31 }),
    ]);

    expect(groupes[0].bestScore).toBe(52);
  });

  it("propose par défaut la candidature la mieux classée pour l'entretien", () => {
    const groupes = grouper([
      match({ application_id: 'a1', semantic_score: 52 }),
      match({ application_id: 'a2', semantic_score: 31 }),
    ]);

    expect(groupes[0].selectedApplicationId).toBe('a1');
    expect(component.candidatureDe(groupes[0]).application_id).toBe('a1');
  });

  it("porte le compte utilisateur, adresse de la fiche back-office", () => {
    // La fiche s'ouvre sur /admin/users/:id — un identifiant d'UTILISATEUR.
    // Prendre le candidate_id mènerait à une page introuvable.
    const groupes = grouper([match({ user_id: 'u42', candidate_id: 'c42' })]);
    expect(groupes[0].userId).toBe('u42');
  });

  it('réunit les compétences des différents CV sans doublon', () => {
    const groupes = grouper([
      match({ application_id: 'a1', skills: ['angular', 'git'] }),
      match({ application_id: 'a2', skills: ['git', 'docker'] }),
    ]);

    expect(groupes[0].skills).toEqual(['angular', 'git', 'docker']);
  });

  // ── Lisibilité du score ──
  //
  // 50 % de proximité sémantique est une FORTE correspondance ; lu comme un
  // pourcentage ordinaire, un RH y voit « la moitié ». Le niveau nommé est ce
  // qui se lit, le chiffre ne fait que l'accompagner.

  it('nomme le niveau de correspondance plutôt que de laisser le chiffre seul', () => {
    expect(component.niveau(52)).toBe('forte');
    expect(component.niveau(50)).toBe('forte');
    expect(component.niveau(49)).toBe('moyenne');
    expect(component.niveau(35)).toBe('moyenne');
    expect(component.niveau(34)).toBe('faible');
    expect(component.niveauLabel(52)).toBe('Forte correspondance');
  });

  // ── Contacter ──

  it("prépare un message nommant l'offre sélectionnée, pas celle de la candidature", () => {
    // La recherche fait remonter des gens qui ont postulé AILLEURS : le
    // message doit parler du poste pour lequel le RH recrute maintenant.
    component.jobs = [{ id: 'j9', title: 'AI Engineer' } as any];
    component.selectedJobId = 'j9';
    const groupe = grouper([match({ job_title: 'Data Engineer' })])[0];

    component.ouvrirContact(groupe);

    expect(component.showContactModal).toBe(true);
    expect(component.contactApplicationId).toBe('a1');
    expect(component.contactMessage).toContain('AI Engineer');
    expect(component.contactMessage).toContain('Alice');
  });
});
