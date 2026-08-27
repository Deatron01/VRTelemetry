```mermaid
graph TD
    A[Source CSS] --> B[PostCSS Processor]
    B --> C[Tailwind CSS Plugin]
    B --> D[Autoprefixer Plugin]
    C --> E[Processed CSS Output]
    D --> E
```
