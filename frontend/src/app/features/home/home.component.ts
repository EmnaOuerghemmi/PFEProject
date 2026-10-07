import { AfterViewInit, Component, ElementRef, OnDestroy, OnInit, QueryList, ViewChild, ViewChildren } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router } from '@angular/router';
import { AuthService } from '../../core/services/auth.service';

@Component({
  selector: 'app-home',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './home.component.html',
  styleUrl: './home.component.css'
})
export class HomeComponent implements OnInit, AfterViewInit, OnDestroy {
  currentUser: any = null;

  /** Panneau déplié dans l'accordéon « Pourquoi travailler avec nous ». */
  activeAdvantage = 0;

  /** Ce que PIQBIT sait faire pour ses clients — nos expertises clés. */
  competencies = [
    {
      icon: 'brain',
      title: 'Orchestration IA',
      desc: "Conception de workflows agentiques sur mesure et d'infrastructures RAG sécurisées pour des groupes internationaux.",
      img: 'https://images.unsplash.com/photo-1620712943543-bcc4688e7485?auto=format&fit=crop&w=900&q=80',
    },
    {
      icon: 'cloud',
      title: "Scalabilité d'infrastructure",
      desc: "Fondations multi-cloud résilientes, conçues pour une forte concurrence d'usage et une disponibilité maximale.",
      img: 'https://images.unsplash.com/photo-1451187580459-43490279c0fa?auto=format&fit=crop&w=900&q=80',
    },
    {
      icon: 'shield-lock',
      title: 'Sécurité de bout en bout',
      desc: "Sécurité dès la conception, à chaque couche applicative, conforme aux normes ISO et référentiels régionaux.",
      img: 'https://images.unsplash.com/photo-1550751827-4bd374c3f58b?auto=format&fit=crop&w=900&q=80',
    },
    {
      icon: 'briefcase',
      title: "Solutions d'entreprise",
      desc: "Développement d'écosystèmes logiciels critiques, taillés pour les appels d'offres publics et privés.",
      img: 'https://images.unsplash.com/photo-1497215728101-856f4ea42174?auto=format&fit=crop&w=900&q=80',
    },
  ];

  /** Indicateurs mis en avant sur le bandeau PIQBIT Labs. */
  stats = [
    { value: '50+', label: 'Déploiements IA' },
    { value: '100%', label: 'Audits de sécurité' },
    { value: '2', label: 'Continents couverts' },
    { value: '99.9%', label: 'Disponibilité garantie' },
  ];

  /** Retours de clients accompagnés en Tunisie et en Europe. */
  testimonials = [
    {
      quote: "PIQBIT a livré notre projet d'infrastructure IT dans les délais et le budget prévus. Leur équipe a démontré une forte expertise technique et maintenu une communication claire tout au long de la mission.",
      name: 'Client entreprise',
      role: 'Secteur privé, Tunisie',
    },
    {
      quote: "La migration cloud et la mise en place DevOps ont été menées avec professionnalisme. PIQBIT a fourni une documentation complète et garanti une conformité totale à nos exigences.",
      name: 'Client institutionnel',
      role: 'Secteur public, Tunisie',
    },
    {
      quote: "Un service soigné, avec une réelle attention aux détails. Le développement sur mesure a répondu à toutes les spécifications, livré avec une documentation et un support appropriés.",
      name: 'Client entreprise',
      role: 'Secteur privé, Europe',
    },
  ];

  /** Gages de conformité affichés en pied de section « Preuves ». */
  certifications = [
    { title: 'Certifié', desc: 'Immatriculé au RNE', tag: 'Tunisie & Europe' },
    { title: 'Conforme', desc: 'TVA & réglementation', tag: 'Couverture de service' },
  ];

  /** Ce qui caractérise notre environnement de travail. */
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
    { num: '01', icon: 'code', name: 'Engineering', desc: 'Frontend · Backend · Mobile',
      img: 'https://images.unsplash.com/photo-1517180102446-f3ece451e9d8?auto=format&fit=crop&w=1000&q=80' },
    { num: '02', icon: 'database', name: 'Data & IA', desc: 'Data Science · ML · Analytics',
      img: 'https://images.unsplash.com/photo-1620712943543-bcc4688e7485?auto=format&fit=crop&w=1000&q=80' },
    { num: '03', icon: 'pencil', name: 'Design', desc: 'UX/UI · Design system',
      img: 'https://images.unsplash.com/photo-1561070791-2526d30994b5?auto=format&fit=crop&w=1000&q=80' },
    { num: '04', icon: 'briefcase', name: 'Corporate', desc: 'RH · Finance · Commercial',
      img: 'https://images.unsplash.com/photo-1497215728101-856f4ea42174?auto=format&fit=crop&w=1000&q=80' },
  ];

  /**
   * « Nos équipes » : un carrousel simple, pas un effet lié au défilement de
   * la page. Les flèches mettent `teamIndex` à jour IMMÉDIATEMENT (repères,
   * bordure active, flèches désactivées ne dépendent pas de l'animation) et
   * lancent le scroll (`track.scrollTo`, pas `slide.scrollIntoView()` — plus
   * fiable pour une piste imbriquée dans une page qui défile aussi). Un
   * geste manuel sur la piste (glissement tactile ou trackpad) est
   * resynchronisé après coup par `syncTeamIndexFromScroll`, sur l'évènement
   * `scroll` de la piste elle-même — pas un `IntersectionObserver` : son
   * callback ne se déclenche pas de façon fiable dans certains contextes
   * embarqués, testé et confirmé sur cette page.
   */
  @ViewChild('teamTrack') teamTrack?: ElementRef<HTMLElement>;
  @ViewChildren('teamSlide') teamSlides!: QueryList<ElementRef<HTMLElement>>;
  teamIndex = 0;
  private teamScrollTimeout?: ReturnType<typeof setTimeout>;
  private readonly onTeamTrackScroll = () => {
    clearTimeout(this.teamScrollTimeout);
    this.teamScrollTimeout = setTimeout(() => this.syncTeamIndexFromScroll(), 120);
  };

  constructor(
    private router: Router,
    private authService: AuthService,
  ) {}

  ngOnInit() {
    this.currentUser = this.authService.getCurrentUser();
    this.authService.currentUser$.subscribe(user => this.currentUser = user);
  }

  ngAfterViewInit() {
    this.teamTrack?.nativeElement.addEventListener('scroll', this.onTeamTrackScroll, { passive: true });
  }

  ngOnDestroy() {
    this.teamTrack?.nativeElement.removeEventListener('scroll', this.onTeamTrackScroll);
    clearTimeout(this.teamScrollTimeout);
  }

  /** La carte dont le bord gauche est le plus proche du scroll actuel
   *  devient la carte active — appelé une fois le glissement de la piste
   *  stabilisé (débounce dans `onTeamTrackScroll`). */
  private syncTeamIndexFromScroll() {
    const track = this.teamTrack?.nativeElement;
    if (!track || !this.teamSlides?.length) return;
    let closest = 0;
    let closestDist = Infinity;
    this.teamSlides.forEach((ref, i) => {
      const dist = Math.abs(ref.nativeElement.offsetLeft - track.scrollLeft);
      if (dist < closestDist) { closestDist = dist; closest = i; }
    });
    this.teamIndex = closest;
  }

  goToTeamSlide(i: number) {
    const clamped = Math.max(0, Math.min(this.teams.length - 1, i));
    const target = this.teamSlides.get(clamped)?.nativeElement;
    const track = this.teamTrack?.nativeElement;
    if (!target || !track) return;
    track.scrollTo({ left: target.offsetLeft, behavior: 'smooth' });
    this.teamIndex = clamped;
  }

  prevTeamSlide() { this.goToTeamSlide(Math.max(0, this.teamIndex - 1)); }
  nextTeamSlide() { this.goToTeamSlide(Math.min(this.teams.length - 1, this.teamIndex + 1)); }

  get isAuthenticated(): boolean {
    return this.authService.isAuthenticated();
  }

  goToJobs() { this.router.navigate(['/frontoffice/jobs']); }
  goToApplications() { this.router.navigate(['/frontoffice/applications']); }
  goToRegister() { this.router.navigate(['/register']); }

  getUserFirstName(): string {
    if (!this.currentUser) return '';
    const name = this.currentUser.full_name || this.currentUser.username || '';
    return name.split(' ')[0];
  }
}
