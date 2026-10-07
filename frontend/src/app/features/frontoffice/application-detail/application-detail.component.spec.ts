import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';
import { of, throwError } from 'rxjs';

import { ApplicationDetailComponent } from './application-detail.component';
import {
  ApplicationScoreDetail, CandidateFeedbackService,
} from '../../../core/services/candidate-feedback.service';
import { JobRecommendation, RecruitmentService } from '../../../core/services/recruitment.service';

/** Un dossier minimal mais complet, surchargeable champ par champ. */
function dossier(over: Partial<ApplicationScoreDetail> = {}): ApplicationScoreDetail {
  return {
    application_id: 'app-1',
    job_offer_id: 'job-0',
    job_title: 'AI Engineer',
    job_description: '',
    job_required_skills: [],
    job_contract_types: [],
    applied_at: '2026-09-22T10:00:00Z',
    status: 'PENDING',
    analysis_ready: true,
    skills_matched: [],
    skills_missing: [],
    skills_required: [],
    observations: [],
    advice: [],
    ...over,
  };
}

/** Une recommandation plausible, surchargeable champ par champ. */
function reco(over: Partial<JobRecommendation> = {}): JobRecommendation {
  return {
    job_id: 'job-1',
    title: 'Ingénieur DevOps',
    compatibility_score: 0.78,
    matching_skills: ['Docker', 'Kubernetes'],
    missing_skills: ['AWS'],
    reasons: ['2 des 3 compétences demandées figurent dans votre CV'],
    ...over,
  };
}

describe('ApplicationDetailComponent', () => {
  let fixture: ComponentFixture<ApplicationDetailComponent>;
  let component: ApplicationDetailComponent;

  /** Monte la page avec la réponse voulue pour les recommandations. */
  async function monter(recommandations: JobRecommendation[] | Error) {
    const feedback = jasmine.createSpyObj<CandidateFeedbackService>(
      'CandidateFeedbackService', ['scoreDetail', 'withdraw']);
    feedback.scoreDetail.and.returnValue(of(dossier()));

    const recruitment = jasmine.createSpyObj<RecruitmentService>(
      'RecruitmentService', ['getMyRecommendedJobs', 'downloadCVAsBlob']);
    recruitment.getMyRecommendedJobs.and.returnValue(
      recommandations instanceof Error
        ? throwError(() => recommandations)
        : of(recommandations));

    await TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        { provide: CandidateFeedbackService, useValue: feedback },
        { provide: RecruitmentService, useValue: recruitment },
        {
          provide: ActivatedRoute,
          useValue: { snapshot: { paramMap: convertToParamMap({ id: 'app-1' }) } },
        },
      ],
      imports: [ApplicationDetailComponent],
    }).compileComponents();

    fixture = TestBed.createComponent(ApplicationDetailComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  }

  const section = () => fixture.nativeElement.querySelector('.ad-card--reco');
  const cartes = () => fixture.nativeElement.querySelectorAll('.ad-reco');

  it('se crée', async () => {
    await monter([]);
    expect(component).toBeTruthy();
  });

  it("n'affiche RIEN quand aucune offre n'atteint le seuil", async () => {
    await monter([]);
    // Exigence explicite : pas de section, donc pas de blanc ni de message
    // d'erreur — l'absence de recommandation n'est pas un incident.
    expect(section()).toBeNull();
  });

  it('affiche la section, son titre et une carte par offre', async () => {
    await monter([reco(), reco({ job_id: 'job-2', title: 'SRE' })]);

    expect(section()).not.toBeNull();
    expect(section().querySelector('.ad-h2').textContent.trim())
      .toBe('Offres recommandées pour vous');
    expect(section().querySelector('.ad-sub--reco').textContent.trim())
      .toBe('Des opportunités sélectionnées selon votre profil et votre CV.');
    expect(cartes().length).toBe(2);
  });

  it('montre le score en pourcentage et les compétences retrouvées', async () => {
    await monter([reco({ compatibility_score: 0.782 })]);

    const carte = cartes()[0].textContent;
    expect(carte).toContain('78 %');          // 0.782 → 78 %, pas 0.782
    expect(carte).toContain('Docker');
    expect(carte).toContain('Kubernetes');
  });

  it('reste silencieux si les recommandations échouent', async () => {
    // Un bonus qui tombe ne doit pas parasiter le dossier, qui est la raison
    // d'être de la page.
    await monter(new Error('500'));

    expect(component.recommandations).toEqual([]);
    expect(section()).toBeNull();
    expect(component.etape).toBe('pret');
    expect(component.erreur).toBe('');
  });
});
