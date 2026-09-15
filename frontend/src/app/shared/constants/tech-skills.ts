/**
 * Liste curée de technologies IT courantes, pour l'auto-complétion du champ
 * « Compétences requises » à la création d'une offre. Recoupe volontairement
 * le vocabulaire du moteur de scoring (backend `nlp_service.SKILLS_DB`) mais
 * avec une casse/orthographe lisible pour l'utilisateur (ex. "Node.js" plutôt
 * que le token normalisé "nodejs").
 */
export const TECH_SKILLS: string[] = [
  // Langages
  'Python', 'Java', 'JavaScript', 'TypeScript', 'C#', 'PHP', 'Ruby', 'Go', 'Rust', 'Kotlin',
  'Swift', 'Objective-C', 'Scala', 'Perl', 'R', 'MATLAB', 'C', 'C++', 'Dart',

  // Frontend
  'HTML', 'CSS', 'Sass', 'Tailwind CSS', 'Bootstrap', 'React', 'Angular', 'Vue.js', 'Svelte',
  'Next.js', 'Nuxt.js', 'Gatsby', 'Redux', 'RxJS',

  // Backend / frameworks
  'Node.js', 'Express.js', 'NestJS', 'Deno', 'FastAPI', 'Django', 'Flask', 'Spring Boot',
  'Spring', 'ASP.NET', 'Laravel', 'Symfony', 'Ruby on Rails',

  // API
  'REST API', 'GraphQL', 'SOAP', 'gRPC', 'WebSocket',

  // Bases de données
  'SQL', 'NoSQL', 'PostgreSQL', 'MySQL', 'MongoDB', 'Redis', 'Elasticsearch', 'Cassandra',
  'Oracle', 'SQL Server', 'SQLite', 'ClickHouse', 'DynamoDB', 'Firebase',

  // Cloud / DevOps
  'AWS', 'Azure', 'GCP', 'Docker', 'Kubernetes', 'Terraform', 'Ansible', 'Jenkins',
  'GitLab CI', 'GitHub Actions', 'Git', 'CI/CD', 'DevOps', 'Linux', 'Bash', 'Nginx',

  // Data / IA
  'Machine Learning', 'Deep Learning', 'TensorFlow', 'PyTorch', 'Keras', 'Scikit-learn',
  'NLP', 'Data Science', 'Big Data', 'Spark', 'Hadoop', 'ETL', 'Pandas', 'NumPy',
  'Power BI', 'Tableau', 'Airflow',

  // Mobile
  'iOS', 'Android', 'Flutter', 'React Native', 'Xamarin',

  // Test / qualité
  'QA', 'Tests automatisés', 'Pytest', 'JUnit', 'Selenium', 'Cypress', 'Jest',

  // Sécurité
  'Sécurité informatique', 'Cryptographie', 'OAuth', 'JWT', 'SSL/TLS', 'Pentest',

  // Architecture
  'Microservices', 'Serverless', 'API Design', 'MVC', 'Architecture logicielle',

  // Design / UX
  'UI/UX Design', 'Figma', 'Sketch', 'Adobe XD', 'Prototypage',

  // Méthodologie / gestion
  'Agile', 'Scrum', 'Kanban', 'Jira', 'Confluence', 'Gestion de projet',

  // Soft skills
  'Communication', 'Leadership', 'Travail en équipe', 'Résolution de problèmes',
  'Gestion du temps', 'Négociation',

  // Langues
  'Anglais', 'Français', 'Arabe', 'Espagnol', 'Allemand', 'Italien',
];
