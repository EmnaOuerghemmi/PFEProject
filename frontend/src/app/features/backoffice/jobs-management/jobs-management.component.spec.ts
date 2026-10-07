import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';
import { By } from '@angular/platform-browser';
import { JobsManagementComponent } from './jobs-management.component';
import { PermissionsService } from '../../../core/services/permissions.service';

describe('JobsManagementComponent', () => {
  let component: JobsManagementComponent;
  let fixture: ComponentFixture<JobsManagementComponent>;
  let permissions: PermissionsService;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
      ],
      imports: [JobsManagementComponent]
    }).compileComponents();

    fixture = TestBed.createComponent(JobsManagementComponent);
    component = fixture.componentInstance;
    permissions = TestBed.inject(PermissionsService);
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  // ── Droits sur les offres ──

  it('verrouille création, modification et suppression pour un recruteur', () => {
    spyOn(permissions, 'peut').and.callFake((ressource: string, action: string) =>
      ressource === 'jobs' && action === 'read');
    fixture.detectChanges();

    expect(component.peutModifierOffres).toBeFalse();
    expect(component.peutSupprimerOffres).toBeFalse();
    // Visible, mais verrouillé (cadenas, non cliquable).
    const creer = fixture.debugElement.query(By.css('.btn--create-offer'));
    expect(creer).not.toBeNull();
    expect(creer.nativeElement.disabled).toBeTrue();
    expect(creer.nativeElement.classList).toContain('is-locked');

    // Même appelées directement, les actions ne font rien.
    component.openCreateDrawer();
    expect(component.drawerOpen).toBeFalse();
  });

  it('propose la création au RH', () => {
    spyOn(permissions, 'peut').and.returnValue(true);
    // Liste des offres chargée : pendant le chargement, le bouton attend (voir le gabarit).
    component.jobsLoading = false;
    fixture.detectChanges();

    const creer = fixture.debugElement.query(By.css('.btn--create-offer'));
    expect(creer.nativeElement.disabled).toBeFalse();
    expect(creer.nativeElement.classList).not.toContain('is-locked');
  });
});
