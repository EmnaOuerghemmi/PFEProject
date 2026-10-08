"""
Dataset Cleaning and Analysis Script
Consolidates multiple salary datasets and extracts:
- Job Titles
- Average Salaries
- Monthly Salaries
- Skills by Job Title
"""

import pandas as pd
from pathlib import Path
from collections import defaultdict

# Define dataset paths
DATASETS_DIR = Path(__file__).parent / "datasets"
OUTPUT_DIR = Path(__file__).parent / "cleaned_data"

# Create output directory if it doesn't exist
OUTPUT_DIR.mkdir(exist_ok=True)


class DatasetCleaner:
    """Main cleaner class for processing salary datasets"""
    
    def __init__(self):
        self.all_data = []
        self.job_titles = set()
        self.skills_by_job = defaultdict(set)
        
    def clean_glassdoor(self):
        """Clean Glassdoor dataset"""
        print("🔄 Processing Glassdoor_Salary_Cleaned_Version.csv...")
        
        try:
            df = pd.read_csv(DATASETS_DIR / "Glassdoor_Salary_Cleaned_Version.csv")
            
            # Clean and standardize
            df = df[df['avg_salary'].notna()]  # Remove null salaries
            df = df[df['avg_salary'] > 0]  # Remove invalid salaries
            
            # Calculate monthly salary
            df['monthly_salary'] = df['avg_salary'] * 1000 / 12
            
            # Standardize column names
            df_clean = pd.DataFrame({
                'job_title': df['Job Title'].str.strip().str.lower(),
                'avg_salary_yearly': df['avg_salary'] * 1000,
                'avg_salary_monthly': df['monthly_salary'],
                'company_name': df['Company Name'],
                'location': df['Location'],
                'rating': df['Rating'],
                'min_salary': df['min_salary'] * 1000,
                'max_salary': df['max_salary'] * 1000,
                'dataset': 'Glassdoor'
            })
            
            # Extract skills
            skills_map = {
                'python': df['python_yn'].astype(int),
                'r_language': df['R_yn'].astype(int),
                'spark': df['spark'].astype(int),
                'aws': df['aws'].astype(int),
                'excel': df['excel'].astype(int)
            }
            
            df_clean = pd.concat([df_clean.reset_index(drop=True), 
                                 pd.DataFrame(skills_map).reset_index(drop=True)], axis=1)
            
            self.all_data.append(df_clean)
            print(f"✅ Glassdoor: {len(df_clean)} records processed")
            
            # Store skills
            for idx, row in df_clean.iterrows():
                job = row['job_title']
                if row['python'] == 1:
                    self.skills_by_job[job].add('Python')
                if row['r_language'] == 1:
                    self.skills_by_job[job].add('R')
                if row['spark'] == 1:
                    self.skills_by_job[job].add('Spark')
                if row['aws'] == 1:
                    self.skills_by_job[job].add('AWS')
                if row['excel'] == 1:
                    self.skills_by_job[job].add('Excel')
            
            return df_clean
            
        except Exception as e:
            print(f"❌ Error processing Glassdoor: {e}")
            return None
    
    def clean_salary_dataset_extra_features(self):
        """Clean Salary_Dataset_with_Extra_Features.csv"""
        print("🔄 Processing Salary_Dataset_with_Extra_Features.csv...")
        
        try:
            df = pd.read_csv(DATASETS_DIR / "Salary_Dataset_with_Extra_Features.csv")
            
            # Clean and standardize
            df = df[df['Salary'].notna()]
            df = df[df['Salary'] > 0]
            
            # Calculate monthly salary
            df['monthly_salary'] = df['Salary'] / 12
            
            # Standardize column names
            df_clean = pd.DataFrame({
                'job_title': df['Job Title'].str.strip().str.lower(),
                'avg_salary_yearly': df['Salary'],
                'avg_salary_monthly': df['monthly_salary'],
                'company_name': df['Company Name'],
                'location': df['Location'],
                'rating': df['Rating'],
                'min_salary': df['Salary'] * 0.85,  # Estimate
                'max_salary': df['Salary'] * 1.15,  # Estimate
                'dataset': 'Salary Dataset Extra Features',
                'job_roles': df['Job Roles'].fillna('')
            })
            
            # Initialize skill columns
            df_clean['python'] = 0
            df_clean['r_language'] = 0
            df_clean['spark'] = 0
            df_clean['aws'] = 0
            df_clean['excel'] = 0
            
            # Extract skills from Job Roles
            for idx, row in df_clean.iterrows():
                roles = str(row['job_roles']).lower()
                job = row['job_title']
                
                if 'python' in roles:
                    df_clean.at[idx, 'python'] = 1
                    self.skills_by_job[job].add('Python')
                if 'r' in roles or 'r-' in roles:
                    df_clean.at[idx, 'r_language'] = 1
                    self.skills_by_job[job].add('R')
                if 'spark' in roles:
                    df_clean.at[idx, 'spark'] = 1
                    self.skills_by_job[job].add('Spark')
                if 'aws' in roles or 'amazon' in roles:
                    df_clean.at[idx, 'aws'] = 1
                    self.skills_by_job[job].add('AWS')
                if 'excel' in roles:
                    df_clean.at[idx, 'excel'] = 1
                    self.skills_by_job[job].add('Excel')
            
            df_clean = df_clean.drop('job_roles', axis=1)
            self.all_data.append(df_clean)
            print(f"✅ Salary Dataset Extra Features: {len(df_clean)} records processed")
            
            return df_clean
            
        except Exception as e:
            print(f"❌ Error processing Salary Dataset Extra Features: {e}")
            return None
    
    def clean_software_professional_salaries(self):
        """Clean Software_Professional_Salaries.csv"""
        print("🔄 Processing Software_Professional_Salaries.csv...")
        
        try:
            df = pd.read_csv(DATASETS_DIR / "Software_Professional_Salaries.csv")
            
            # Clean and standardize
            df = df[df['Salary'].notna()]
            df = df[df['Salary'] > 0]
            
            # Calculate monthly salary
            df['monthly_salary'] = df['Salary'] / 12
            
            # Standardize column names
            df_clean = pd.DataFrame({
                'job_title': df['Job Title'].str.strip().str.lower(),
                'avg_salary_yearly': df['Salary'],
                'avg_salary_monthly': df['monthly_salary'],
                'company_name': df['Company Name'],
                'location': df['Location'],
                'rating': df['Rating'],
                'min_salary': df['Salary'] * 0.85,  # Estimate
                'max_salary': df['Salary'] * 1.15,  # Estimate
                'dataset': 'Software Professional Salaries',
                'python': 0,
                'r_language': 0,
                'spark': 0,
                'aws': 0,
                'excel': 0
            })
            
            # Extract skills from job title
            for idx, row in df_clean.iterrows():
                job = row['job_title']
                
                if 'python' in job:
                    df_clean.at[idx, 'python'] = 1
                    self.skills_by_job[job].add('Python')
                if 'r' in job or 'r ' in job:
                    df_clean.at[idx, 'r_language'] = 1
                    self.skills_by_job[job].add('R')
                if 'spark' in job:
                    df_clean.at[idx, 'spark'] = 1
                    self.skills_by_job[job].add('Spark')
                if 'aws' in job or 'amazon' in job:
                    df_clean.at[idx, 'aws'] = 1
                    self.skills_by_job[job].add('AWS')
                if 'excel' in job:
                    df_clean.at[idx, 'excel'] = 1
                    self.skills_by_job[job].add('Excel')
            
            self.all_data.append(df_clean)
            print(f"✅ Software Professional Salaries: {len(df_clean)} records processed")
            
            return df_clean
            
        except Exception as e:
            print(f"❌ Error processing Software Professional Salaries: {e}")
            return None
    
    def consolidate_data(self):
        """Consolidate all cleaned datasets"""
        print("\n📊 Consolidating all datasets...")
        
        if not self.all_data:
            print("❌ No data to consolidate")
            return None
        
        # Concatenate all data
        consolidated = pd.concat(self.all_data, ignore_index=True)
        
        # Sort by average salary
        consolidated = consolidated.sort_values('avg_salary_yearly', ascending=False)
        
        print(f"✅ Total records consolidated: {len(consolidated)}")
        
        return consolidated
    
    def generate_job_analysis(self, consolidated_df):
        """Generate job title analysis"""
        print("\n📈 Generating job title analysis...")
        
        # Group by job title
        job_analysis = consolidated_df.groupby('job_title').agg({
            'avg_salary_yearly': ['mean', 'median', 'min', 'max', 'count'],
            'avg_salary_monthly': 'mean',
            'rating': 'mean'
        }).round(2)
        
        job_analysis.columns = ['avg_salary_yearly_mean', 'avg_salary_yearly_median',
                                'avg_salary_yearly_min', 'avg_salary_yearly_max',
                                'count_records', 'avg_salary_monthly_mean', 'avg_rating']
        
        job_analysis = job_analysis.sort_values('count_records', ascending=False)
        
        # Add skills
        job_analysis['skills'] = job_analysis.index.map(
            lambda x: ', '.join(sorted(self.skills_by_job.get(x, set())))
        )
        
        print(f"✅ Job analysis generated: {len(job_analysis)} unique job titles")
        
        return job_analysis
    
    def save_results(self, consolidated_df, job_analysis):
        """Save cleaned data and analysis to CSV"""
        print("\n💾 Saving results...")
        
        # Save consolidated data
        consolidated_file = OUTPUT_DIR / "consolidated_salary_data.csv"
        consolidated_df.to_csv(consolidated_file, index=False)
        print(f"✅ Consolidated data saved: {consolidated_file}")
        
        # Save job analysis
        analysis_file = OUTPUT_DIR / "job_salary_analysis.csv"
        job_analysis.to_csv(analysis_file)
        print(f"✅ Job analysis saved: {analysis_file}")
        
        # Save top 10 jobs by average salary
        top_jobs_file = OUTPUT_DIR / "top_10_jobs_by_salary.csv"
        job_analysis.head(10).to_csv(top_jobs_file)
        print(f"✅ Top 10 jobs saved: {top_jobs_file}")
        
        # Save skills analysis
        skills_file = OUTPUT_DIR / "skills_by_job.csv"
        skills_df = pd.DataFrame({
            'job_title': list(self.skills_by_job.keys()),
            'skills': [', '.join(sorted(v)) for v in self.skills_by_job.values()]
        })
        skills_df = skills_df.sort_values('job_title')
        skills_df.to_csv(skills_file, index=False)
        print(f"✅ Skills analysis saved: {skills_file}")
        
        print(f"\n✨ All files saved to: {OUTPUT_DIR}")
    
    def run(self):
        """Execute the complete cleaning pipeline"""
        print("=" * 60)
        print("🚀 Starting Dataset Cleaning Pipeline")
        print("=" * 60 + "\n")
        
        # Clean individual datasets
        self.clean_glassdoor()
        self.clean_salary_dataset_extra_features()
        self.clean_software_professional_salaries()
        
        # Consolidate
        consolidated = self.consolidate_data()
        if consolidated is None:
            return
        
        # Generate analysis
        job_analysis = self.generate_job_analysis(consolidated)
        
        # Save results
        self.save_results(consolidated, job_analysis)
        
        # Print summary
        self.print_summary(consolidated, job_analysis)
    
    def print_summary(self, consolidated_df, job_analysis):
        """Print summary statistics"""
        print("\n" + "=" * 60)
        print("📊 SUMMARY STATISTICS")
        print("=" * 60)
        
        print(f"\nTotal Records: {len(consolidated_df):,}")
        print(f"Unique Job Titles: {len(job_analysis):,}")
        print(f"Unique Companies: {consolidated_df['company_name'].nunique():,}")
        print(f"Unique Locations: {consolidated_df['location'].nunique():,}")
        
        print("\n💰 Salary Statistics (Yearly):")
        print(f"  Average: ${consolidated_df['avg_salary_yearly'].mean():,.2f}")
        print(f"  Median:  ${consolidated_df['avg_salary_yearly'].median():,.2f}")
        print(f"  Min:     ${consolidated_df['avg_salary_yearly'].min():,.2f}")
        print(f"  Max:     ${consolidated_df['avg_salary_yearly'].max():,.2f}")
        
        print("\n💼 Top 5 Highest Paying Jobs:")
        top_5 = job_analysis.nlargest(5, 'avg_salary_yearly_mean')
        for idx, (job_title, row) in enumerate(top_5.iterrows(), 1):
            print(f"  {idx}. {job_title.title()}")
            print(f"     Average: ${row['avg_salary_yearly_mean']:,.2f}/year")
            print(f"     Monthly: ${row['avg_salary_monthly_mean']:,.2f}")
            print(f"     Records: {int(row['count_records'])}")
            if row['skills']:
                print(f"     Skills: {row['skills']}")
        
        print(f"\n⭐ Average Rating: {consolidated_df['rating'].mean():.2f}/5.0")
        
        print("\n" + "=" * 60)


if __name__ == "__main__":
    cleaner = DatasetCleaner()
    cleaner.run()
