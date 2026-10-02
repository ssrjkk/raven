class ToolExplorer {
    constructor() {
        this.grid = document.getElementById('tools-grid');
        this.searchInput = document.getElementById('tool-search');
        this.filterBtns = document.querySelectorAll('.filter-btn');
        this.activeCategory = 'all';
        this.searchQuery = '';
        this.init();
    }

    init() {
        this.render();
        this.searchInput.addEventListener('input', (e) => {
            this.searchQuery = e.target.value.toLowerCase();
            this.render();
        });
        this.filterBtns.forEach(btn => {
            btn.addEventListener('click', () => {
                this.filterBtns.forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                this.activeCategory = btn.dataset.category;
                this.render();
            });
        });
    }

    getFilteredTools() {
        return TOOLS_DATA.filter(tool => {
            const matchesCategory = this.activeCategory === 'all' || tool.category === this.activeCategory;
            const matchesSearch = !this.searchQuery
                || tool.name.toLowerCase().includes(this.searchQuery)
                || tool.description.toLowerCase().includes(this.searchQuery);
            return matchesCategory && matchesSearch;
        });
    }

    render() {
        const tools = this.getFilteredTools();
        this.grid.innerHTML = '';

        if (tools.length === 0) {
            this.grid.innerHTML = '<div class="no-results">No tools match your search</div>';
            return;
        }

        tools.forEach(tool => {
            const card = document.createElement('div');
            card.className = 'tool-card';
            const paramsHtml = Object.entries(tool.params)
                .map(([k, v]) => `<span class="param">${k}: <span class="param-type">${v}</span></span>`)
                .join('');
            card.innerHTML = `
                <div class="tool-card-header">
                    <span class="tool-name">${tool.name}</span>
                    <span class="tool-category-badge">${tool.category}</span>
                </div>
                <p class="tool-desc">${tool.description}</p>
                <div class="tool-params">${paramsHtml || '<span class="param no-params">no parameters</span>'}</div>
            `;
            this.grid.appendChild(card);
        });
    }
}

document.addEventListener('DOMContentLoaded', () => {
    new ToolExplorer();
    new TerminalDemo();

    document.querySelectorAll('a[href^="#"]').forEach(link => {
        link.addEventListener('click', (e) => {
            const target = document.querySelector(link.getAttribute('href'));
            if (target) {
                e.preventDefault();
                target.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }
        });
    });

    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.classList.add('visible');
            }
        });
    }, { threshold: 0.1 });

    document.querySelectorAll('.section').forEach(section => {
        observer.observe(section);
    });
});
