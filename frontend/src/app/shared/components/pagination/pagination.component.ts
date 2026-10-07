import { Component, Input, Output, EventEmitter } from '@angular/core';
import { CommonModule } from '@angular/common';

@Component({
  selector: 'app-pagination',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './pagination.component.html',
  styleUrls: ['./pagination.component.css']
})
export class PaginationComponent {
  @Input() currentPage = 1;
  @Input() totalPages = 1;
  @Input() total = 0;
  @Input() pageSize = 10;
  /** Masque le choix « N / page » quand l'appelant impose une taille fixe. */
  @Input() showPageSize = true;
  @Output() pageChange = new EventEmitter<number>();
  @Output() pageSizeChange = new EventEmitter<number>();

  readonly pageSizeOptions = [5, 10, 25, 50];
  sizeMenuOpen = false;

  get itemsStart() {
    return this.total === 0 ? 0 : (this.currentPage - 1) * this.pageSize + 1;
  }

  get itemsEnd() {
    return Math.min(this.currentPage * this.pageSize, this.total);
  }

  goToPage(page: number) {
    if (page >= 1 && page <= this.totalPages && page !== this.currentPage) {
      this.pageChange.emit(page);
    }
  }

  onPageSizeChange() {
    this.pageSizeChange.emit(Number(this.pageSize));
  }

  toggleSizeMenu() { this.sizeMenuOpen = !this.sizeMenuOpen; }

  selectPageSize(size: number) {
    this.pageSize = size;
    this.sizeMenuOpen = false;
    this.onPageSizeChange();
  }
}
