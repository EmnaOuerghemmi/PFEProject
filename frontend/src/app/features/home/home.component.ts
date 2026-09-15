import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router } from '@angular/router';
import {
  contractTypesLabel,
  JobOffer,
  RecruitmentService,
  WORK_MODE_LABELS,
} from '../../core/services/recruitment.service';
import { AuthService } from '../../core/services/auth.service';

@Component({
  selector: 'app-home',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './home.component.html',
  styleUrl: './home.component.css'
})
export class HomeComponent implements OnInit {
  totalJobs = 0;
  currentUser: any = null;

  /**
   * Les postes affichés dans le sommaire du hero.
   *
   * Le hero annonçait jusqu'ici un simple compteur : un candidat arrivait sur
   * l'accueil sans voir un seul intitulé. On y liste désormais les offres les
   * plus récentes, tirées de l'API — jamais de données de démonstration : un
   * sommaire vide est plus honnête qu'un sommaire inventé.
   */
  openRoles: JobOffer[] = [];

  /** Ce qui caractérise PIQBIT en tant que société de services. */
  advantages = [
    {
      icon: 'stack',
      title: 'Expertise technique complète',
      desc: "Maîtrise du cycle de développement dans son ensemble, de la conception à la maintenance. Expertise des architectures modernes (Next.js, NestJS, Symfony, React, Vue.js) et spécialisation en intégration d'IA et de LLM.",
      img: 'https://images.unsplash.com/photo-1461749280684-dccba630e2f6?auto=format&fit=crop&w=900&q=80',
    },
    {
      icon: 'growth',
      title: 'Qualité & performance',
      desc: "Code propre et documenté, conforme aux standards du métier. Architecture évolutive et maintenable. Tests automatisés en méthodologie TDD/BDD, avec une couverture complète.",
      img: 'https://images.unsplash.com/photo-1551288049-bebda4e38f71?auto=format&fit=crop&w=900&q=80',
    },
    {
      icon: 'shield',
      title: 'Conformité & professionnalisme',
      desc: "Respect strict des normes légales tunisiennes. Facturation transparente et conforme en matière de TVA. Contrats clairs et protection des données clients. Communication régulière et reporting détaillé.",
      img: 'https://images.unsplash.com/photo-1450101499163-c8848c66ca85?auto=format&fit=crop&w=900&q=80',
    },
    {
      icon: 'users',
      title: 'Approche orientée client',
      desc: "Écoute attentive des besoins métier. Conseil stratégique et recommandations techniques. Méthodologie agile avec livraisons itératives. Formation des équipes clientes, support réactif et maintenance évolutive.",
      img: 'https://images.unsplash.com/photo-1600880292203-757bb62b4baf?auto=format&fit=crop&w=900&q=80',
    },
  ];

  /** Le parcours du candidat, décrit de son point de vue uniquement. */
  process = [
    { num: '01', title: 'Créez votre compte', desc: "Inscrivez-vous en quelques minutes avec votre adresse e-mail. Un lien de confirmation active votre espace candidat." },
    { num: '02', title: 'Complétez votre profil', desc: "Renseignez votre parcours et déposez votre CV. Votre profil est réutilisé à chaque candidature : vous ne le saisissez qu'une seule fois." },
    { num: '03', title: 'Postulez à une offre', desc: "Parcourez les postes ouverts et candidatez en un clic depuis la page de l'offre qui vous intéresse." },
    { num: '04', title: 'Suivez vos candidatures', desc: "Consultez l'avancement de chaque candidature depuis votre espace, et recevez une notification à chaque changement d'étape." },
  ];

  /** Domaines dans lesquels PIQBIT recrute. */
  teams = [
    { name: 'Engineering', desc: 'Frontend · Backend · Mobile',
      img: 'https://images.unsplash.com/photo-1517180102446-f3ece451e9d8?auto=format&fit=crop&w=1000&q=80' },
    { name: 'Data & IA', desc: 'Data Science · ML · Analytics',
      img: 'https://images.unsplash.com/photo-1620712943543-bcc4688e7485?auto=format&fit=crop&w=1000&q=80' },
    { name: 'Design', desc: 'UX/UI · Design system',
      img: 'https://images.unsplash.com/photo-1561070791-2526d30994b5?auto=format&fit=crop&w=1000&q=80' },
    { name: 'Corporate', desc: 'RH · Finance · Commercial',
      img: 'https://images.unsplash.com/photo-1497215728101-856f4ea42174?auto=format&fit=crop&w=1000&q=80' },
  ];

  constructor(
    private router: Router,
    private recruitmentService: RecruitmentService,
    private authService: AuthService
  ) {}

  ngOnInit() {
    this.currentUser = this.authService.getCurrentUser();
    this.authService.currentUser$.subscribe(user => this.currentUser = user);
    this.loadJobs();
  }

  /**
   * Alimente le sommaire du hero : le total, et les quatre offres les plus
   * récentes. Une seule requête sert les deux — la page Offres reste la vue
   * complète, l'accueil n'en donne qu'un aperçu.
   */
  loadJobs() {
    this.recruitmentService.getJobs(1, 4).subscribe({
      next: res => {
        this.totalJobs = res.total;
        this.openRoles = res.items ?? [];
      },
      error: () => {
        this.totalJobs = 0;
        this.openRoles = [];
      }
    });
  }

  /**
   * Étiquette courte affichée en regard d'un poste dans le sommaire.
   *
   * On privilégie le mode de travail (l'information que les candidats
   * regardent en premier), avec repli sur le type de contrat puis sur une
   * mention neutre — jamais de case vide, qui casserait l'alignement des
   * points de conduite.
   */
  roleMeta(job: JobOffer): string {
    return (job.work_mode ? WORK_MODE_LABELS[job.work_mode] : null)
        ?? (job.contract_types?.length ? contractTypesLabel(job.contract_types) : null)
        ?? 'Poste ouvert';
  }

  get isAuthenticated(): boolean {
    return this.authService.isAuthenticated();
  }

  goToJob(id: string) { this.router.navigate(['/frontoffice/job', id]); }
  goToJobs() { this.router.navigate(['/frontoffice/jobs']); }
  goToApplications() { this.router.navigate(['/frontoffice/applications']); }
  goToRegister() { this.router.navigate(['/register']); }

  getUserFirstName(): string {
    if (!this.currentUser) return '';
    const name = this.currentUser.full_name || this.currentUser.username || '';
    return name.split(' ')[0];
  }
}
