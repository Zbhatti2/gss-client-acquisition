"""
Seed data for GSS's lookup tables (Table Maintenance's tenant-scoped
lookups) plus the GLOBAL geography tables (regions/countries/states/
cities/country_phone_codes).

GSS trims TMS's seed_data.py down to just the modules GSS actually has —
Contacts, Organizations, Documents & Knowledge Base — and drops every
tourism/HR-specific seed (Suppliers, Points of Interest, Employees,
External Resources, Service/Product taxonomies, Host Organization, and the
Pakistan-geography/Gurdwara/Nankana-Sahib pilot demo data). The starter
values below for Organization Types and Contact Contexts are re-picked for
a client-acquisition CRM rather than reused from TMS's tourism-operator
list; the rest (Contact Categories/Titles/Suffixes/Professions, the
geography tables, and the _slug/_seed_simple/_seed_states helper pattern)
are carried over largely as-is, since none of that is tourism-specific.

Countries use the full ISO 3166-1 alpha-2 list (minus 8 uninhabited/
no-permanent-population territories), same source/rationale as TMS's
version of this file. `states` is seeded with all 50 US states + DC, plus
Canada's 10 provinces and 3 territories — the two countries most likely to
need state-level detail for a US-based tenant; extending this to another
country's subdivisions is a matter of adding another _seed_states() call.

`cities` is seeded for the US only (all 50 states + DC covered), from the
GeoNames "cities1000"/"cities15000" gazetteer (geonamescache PyPI package,
GeoNames data licensed CC BY 4.0 — https://www.geonames.org/), filtered to
incorporated places/populated places with population over ~15,000 — see
US_CITIES below. TMS itself never shipped general-purpose city data (only
a small hand-entered Pakistan/Gurdwara-tour demo list unrelated to GSS's
client-acquisition use case), so this list was sourced independently
rather than carried over from TMS. Other countries still fall back to the
address forms' free-text city_text field until asked for; extending this
to another country is a matter of adding another per-province city dict
(same shape as US_CITIES below) and looping it through _seed_cities the
same way seed_global_lookups() does for the US.

Safe to re-run: uses INSERT OR IGNORE keyed on each table's `code` (states
are additionally scoped by country_id; cities have no code at all, so they
use a manual existence check instead — see _seed_cities).
"""

CONTACT_CATEGORIES = [
    "Personal", "Classmate in Institution", "Colleague in Organization",
    "Friend", "Immediate Family", "Close Relative", "Distant Relative",
    "Doctor", "Lawyer", "Teacher", "Accountant", "Knowledge Expert",
]

CONTACT_TITLES = [
    "Mr.", "Mrs.", "Miss", "Dr.", "Rai.", "Sir.", "Lord.", "Hon.", "Eng.",
    "Dame", "Lady", "Madam", "Justice.",
]

CONTACT_SUFFIXES = [
    "PhD.", "Barrister", "Retd.", "Jr.", "Sr.", "SJ.", "HJ.", "Esq.",
    "CPA.", "M.D.", "D.D.S.", "D.V.M.",
]

PROFESSIONS = [
    "Plumber", "Electrician", "Carpenter", "Welder", "Masonry", "Painter",
    "Decorator", "Cook", "Baby Sitter", "Security Guard", "General Help",
    "Registered Nurse", "Dentist", "Physician", "Seamstress", "Handyman",
    "Cleaner", "Driver", "Auto Mechanic", "Teacher", "Tutor", "Gardener",
    "Architect", "Engineer", "Pilot", "Waiter", "Personal Care",
]

# Re-picked for GSS's client-acquisition focus (TMS's version of this list
# was tourism-specific: "Sikh Tourism", "Resort Guest", etc.).
CONTACT_CONTEXTS = [
    "Prospect", "Client", "Vendor", "Partner", "Referral Source",
    "Investor", "Software Dev.", "AI Expert",
]

# Re-picked for GSS (TMS's version was a tourism-operator's own vendor/
# facility list — hotels, airlines, resorts — not what a client-acquisition
# platform tracks its organizations as).
ORGANIZATION_TYPES = [
    "Prospect", "Client", "Partner", "Vendor", "Competitor",
    "Referral Source", "Investor", "Media/Press", "Government/Regulatory",
    "Nonprofit", "Other",
]

# An organization's several address locations — schema.sql's
# organization_address_types lookup, used by organization_addresses.
ORGANIZATION_ADDRESS_TYPES = ["Mailing Address", "Physical Address"]

# An organization's several phone numbers — schema.sql's
# organization_phone_types lookup, used by organization_phones.
ORGANIZATION_PHONE_TYPES = ["Office", "Mobile", "Fax"]

# Lookup for organizations.size_category_id — a coarse headcount bucket.
# (label, description, min_employees, max_employees) — max_employees is
# None for the open-ended top band. description is the human-readable
# range shown next to the label; min/max drive the form's auto-suggest
# from a typed Number of Employees value.
ORGANIZATION_SIZE_CATEGORIES = [
    ("Small", "Fewer than 10", 0, 9),
    ("Medium-Small", "10 to 49", 10, 49),
    ("Medium", "50 to 249", 50, 249),
    ("Large", "250 or more", 250, None),
]

# Lookup for organizations.organization_domain_id — the industry/sector an
# organization operates in. Sourced from the user-supplied
# domains_and_subdomains.csv (593 raw rows, deduplicated down to 577
# unique (Domain, SubDomain) pairs across 52 domains — the source file had
# a "small business/local services" addendum appended after the main
# industry list that re-listed a number of domain/subdomain pairs already
# present earlier, e.g. "Architecture & Construction, Handyman Services"
# and "Real Estate & Property, Property Management" each appeared twice
# verbatim; kept once, in first-seen order).
ORGANIZATION_DOMAINS = [
    'Agriculture & Farming',
    'Airlines & Aviation',
    'Apparel & Fashion',
    'Architecture & Construction',
    'Arts & Culture',
    'Automotive Manufacturing',
    'Banking & Financial Services',
    'Beverage Production',
    'Biotechnology',
    'Chemical Manufacturing',
    'Cybersecurity',
    'Defense & Aerospace',
    'Education & E-Learning',
    'Electrical & Electronics',
    'Energy & Utilities',
    'Environmental Services',
    'Event Management',
    'Film & Cinema',
    'Food Processing',
    'Gaming & Esports',
    'Government & Public Administration',
    'Healthcare & Hospitals',
    'Hospitality & Lodging',
    'Human Resources',
    'Information Technology (IT)',
    'Insurance',
    'Legal & Law Firms',
    'Logistics & Supply Chain',
    'Manufacturing (General)',
    'Marketing & Advertising',
    'Media & Entertainment',
    'Medical Devices',
    'Metals & Mining',
    'Non-Profit & NGOs',
    'Oil & Gas',
    'Pharmaceuticals',
    'Real Estate & Property',
    'Retail (Brick & Mortar)',
    'Robotics & Automation',
    'Semiconductors',
    'Social Media & Internet',
    'Software (SaaS & Enterprise)',
    'Sports & Athletics',
    'Staffing & Recruitment',
    'Telecommunications',
    'Tourism & Travel',
    'Transportation',
    'Venture Capital & Private Equity',
    'Waste Management',
    'Wholesale & Distribution',
    'Automotive Services',
    'Local Services & Trades',
]

# Nested under ORGANIZATION_DOMAINS (one level, same pattern as
# KNOWLEDGE_SUBDOMAINS/CONTENT_SUBTYPES elsewhere in this file).
ORGANIZATION_SUBDOMAINS = {
    'Agriculture & Farming': [
        'Crop Production (Corn, Wheat, Soy)',
        'Livestock & Poultry',
        'Aquaculture & Fisheries',
        'Agritech (Precision Farming)',
        'Organic Farming',
        'Dairy Farming',
        'Agroforestry',
        'Hydroponics & Vertical Farming',
        'Pesticide & Fertilizer Production',
        'Farm Equipment Manufacturing',
    ],
    'Airlines & Aviation': [
        'Commercial Passenger Airlines',
        'Cargo & Freight Aviation',
        'Private Jet & Charter Services',
        'Aircraft Manufacturing (OEM)',
        'Aerospace Parts & Maintenance (MRO)',
        'Airport Operations & Ground Handling',
        'Air Traffic Control Systems',
        'Space Tourism & Exploration',
        'Drone Delivery Services',
        'Aviation Fuel & Logistics',
    ],
    'Apparel & Fashion': [
        'Luxury/Designer Goods',
        'Fast Fashion Retail',
        'Sportswear & Activewear',
        'Textile & Fabric Manufacturing',
        'Footwear',
        'Accessories (Jewelry, Bags, Watches)',
        'Uniforms & Workwear',
        "Children's Wear",
        'Lingerie & Intimates',
        'Sustainable/Eco-Fashion',
        'Tailoring & Alterations',
        'Custom Dressmaking',
    ],
    'Architecture & Construction': [
        'Residential Construction',
        'Commercial & Industrial Construction',
        'Heavy Civil Engineering (Roads, Bridges)',
        'Architectural Design & Planning',
        'Building Materials Supply',
        'Interior Fit-Outs',
        'Landscaping & Exteriors',
        'Renovation & Remodeling',
        'Modular/Prefab Construction',
        'Green/Sustainable Building',
        'Handyman Services',
        'Remodeling & Renovation',
        'Flooring Installation',
        'Building Materials Supply (for small suppliers)',
    ],
    'Arts & Culture': [
        'Fine Arts (Painting, Sculpture)',
        'Performing Arts (Theater, Dance)',
        'Museums & Galleries',
        'Cultural Heritage Sites',
        'Public Art Installations',
        'Art Dealerships & Auctions',
        'Craftsmanship & Handicrafts',
        'Literature & Poetry',
        'Photography',
        'Cultural Festivals & Events',
    ],
    'Automotive Manufacturing': [
        'Passenger Vehicles (Sedans, SUVs)',
        'Electric Vehicles (EV)',
        'Commercial Trucks & Buses',
        'Auto Parts & Components',
        'Autonomous/Self-Driving Tech',
        'Motorcycles & Scooters',
        'Luxury/Performance Cars',
        'Fleet & Leasing Vehicles',
        'Automotive Design & Styling',
        'Aftermarket Accessories',
        'Auto Mechanics (General Repair)',
        'Collision & Body Shops',
        'Tire & Alignment Services',
        'Fleet Maintenance',
    ],
    'Banking & Financial Services': [
        'Retail Banking (Deposits, Mortgages)',
        'Investment Banking (M&A, IPOs)',
        'Wealth & Asset Management',
        'Private Equity & Venture Capital',
        'Insurance (Life, Health, P&C)',
        'Credit Cards & Payments',
        'Foreign Exchange (Forex)',
        'Microfinance',
        'Central Banking',
        'Trade Finance',
        'Accounting & Bookkeeping',
        'Tax Preparation',
        'Tax Preparation Services',
        'Small Business Payroll',
        'Financial Planning for Individuals',
    ],
    'Beverage Production': [
        'Carbonated Soft Drinks',
        'Alcoholic Beverages (Beer, Wine, Spirits)',
        'Functional Drinks (Energy, Sports)',
        'Bottled Water',
        'Dairy Beverages (Milk, Yogurt drinks)',
        'Tea & Coffee Processing',
        'Juices & Smoothies',
        'Plant-Based Milks',
        'Concentrates & Syrups',
        'Beverage Canning/Bottling Services',
    ],
    'Biotechnology': [
        'Pharmaceuticals (Drug Discovery)',
        'Agricultural Biotech (GMOs)',
        'Industrial Enzymes',
        'Medical Diagnostics',
        'Gene Therapy & CRISPR',
        'Biofuels & Renewable Chemicals',
        'Bioinformatics',
        'Nutraceuticals',
        'Veterinary Biotech',
        'Tissue Engineering',
    ],
    'Chemical Manufacturing': [
        'Industrial Gases',
        'Petrochemicals (Plastics, Resins)',
        'Specialty Chemicals (Adhesives, Coatings)',
        'Agricultural Chemicals (Fertilizers, Pesticides)',
        'Pigments & Dyes',
        'Soaps & Detergents',
        'Explosives & Propellants',
        'Water Treatment Chemicals',
        'Electronic Chemicals',
        'Essential Oils & Flavors',
    ],
    'Cybersecurity': [
        'Network Security (Firewalls, VPNs)',
        'Endpoint Security (Antivirus, EDR)',
        'Cloud Security',
        'Identity & Access Management (IAM)',
        'Data Encryption & Privacy',
        'Risk & Compliance Solutions',
        'Security Operations (SOC)',
        'Threat Intelligence',
        'Blockchain Security',
        'IoT Security',
    ],
    'Defense & Aerospace': [
        'Military Aircraft & Drones',
        'Naval Vessels & Submarines',
        'Ground Combat Systems (Tanks, Missiles)',
        'Weapons & Ammunition',
        'Surveillance & Reconnaissance',
        'Cybersecurity for Defense',
        'Space Defense Systems',
        'Defense Logistics & Support',
        'Training & Simulation',
        'Body Armor & Personnel Protection',
    ],
    'Education & E-Learning': [
        'K-12 Primary/Secondary Education',
        'Higher Education (Universities)',
        'Vocational & Technical Training',
        'Online Course Platforms (MOOCs)',
        'Corporate Training & L&D',
        'EdTech Software (LMS)',
        'Tutoring & Test Prep',
        'Language Learning',
        'Early Childhood Education',
        'Educational Publishing',
        'Babysitting & Nanny Services',
        'Daycare & Childcare Centers',
        'Babysitting/Nanny Services',
        'Daycare & Early Childhood Education',
        'Tutoring Services',
    ],
    'Electrical & Electronics': [
        'Consumer Electronics (TVs, Smartphones)',
        'Semiconductors & Chips',
        'Industrial Electronics',
        'Electronic Components (Capacitors, Connectors)',
        'Batteries & Energy Storage',
        'Home Appliances',
        'Lighting (LED, Smart Lighting)',
        'Wiring & Cabling',
        'Power Distribution Equipment',
        'Sensors & Actuators',
    ],
    'Energy & Utilities': [
        'Oil & Gas Exploration (Upstream)',
        'Natural Gas Distribution',
        'Renewable Energy (Solar, Wind, Hydro)',
        'Nuclear Power',
        'Electric Grid Transmission',
        'Energy Trading & Marketing',
        'Geothermal Energy',
        'Waste-to-Energy',
        'Hydrogen Fuel Production',
        'Utility Billing & Customer Service',
    ],
    'Environmental Services': [
        'Waste Management & Recycling',
        'Water & Wastewater Treatment',
        'Air Quality Monitoring',
        'Environmental Consulting',
        'Ecological Restoration',
        'Carbon Offset/Credits Trading',
        'Hazardous Material Cleanup',
        'Renewable Energy Consulting',
        'Environmental Testing Labs',
        'Conservation & Wildlife Management',
        'Tree Service / Arboriculture',
        'Lawn Care & Landscaping',
        'Pool Maintenance & Cleaning',
        'Pest Control',
        'Janitorial & Commercial Cleaning',
        'Junk Removal',
        'Janitorial Services',
        'Carpet Cleaning',
        'Window Cleaning',
        'Power Washing',
        'Biohazard Cleanup',
    ],
    'Event Management': [
        'Corporate Conferences & Summits',
        'Weddings & Social Events',
        'Music Concerts & Festivals',
        'Sports Event Management',
        'Trade Shows & Expos',
        'Virtual/Hybrid Events',
        'Awards Ceremonies',
        'Private Parties & Galas',
        'Event Logistics (AV, Staging)',
        'Destination Management',
    ],
    'Film & Cinema': [
        'Motion Picture Production',
        'Animation Studios',
        'Film Distribution',
        'Movie Theaters (Exhibition)',
        'Post-Production (Editing, VFX)',
        'Documentary Filmmaking',
        'Short Films',
        'Film Equipment Rental',
        'Casting Agencies',
        'Film Festivals',
    ],
    'Food Processing': [
        'Meat & Poultry Processing',
        'Dairy Processing (Cheese, Yogurt)',
        'Grain & Cereal Milling',
        'Bakery & Confectionery',
        'Frozen Food Production',
        'Canned & Preserved Foods',
        'Snack Food Manufacturing',
        'Plant-Based Meat Alternatives',
        'Spices & Seasonings',
        'Baby Food Production',
    ],
    'Gaming & Esports': [
        'Video Game Development (AAA)',
        'Mobile Gaming',
        'Esports Organizations & Leagues',
        'Game Streaming Platforms',
        'Game Publishing',
        'VR/AR Gaming',
        'Fantasy Sports',
        'Casino & Gambling (iGaming)',
        'Game Engine Development (Unity, Unreal)',
        'Gaming Hardware (Consoles, Peripherals)',
    ],
    'Government & Public Administration': [
        'Federal/National Government',
        'State/Provincial Government',
        'Municipal/Local Government',
        'Public Infrastructure (Roads, Utilities)',
        'Defense & National Security',
        'Public Health Agencies',
        'Education Departments',
        'Tax & Revenue Services',
        'Justice & Law Enforcement',
        'Regulatory Agencies',
    ],
    'Healthcare & Hospitals': [
        'General Acute Care Hospitals',
        'Specialty Clinics (Cardiology, Ortho)',
        'Primary Care & Urgent Care',
        'Mental Health & Psychiatry',
        'Outpatient Surgery Centers',
        'Rehabilitation & Physical Therapy',
        'Home Healthcare Services',
        'Hospice & Palliative Care',
        'Medical Laboratories',
        'Telemedicine Platforms',
        'In-Home Elderly Care',
        'Hospice Care',
        'Elderly/In-Home Care',
        'Senior Day Centers',
        'Home Health Aides',
    ],
    'Hospitality & Lodging': [
        'Luxury Hotels & Resorts',
        'Budget/Motel Chains',
        'Boutique Hotels',
        'Timeshare & Vacation Rentals',
        'Hostels & Backpackers',
        'Bed & Breakfasts',
        'Serviced Apartments',
        'Casino Hotels',
        'Eco-Lodges & Glamping',
        'Hotel Management Services',
        'Barber Shops',
        'Hair & Nail Salons',
        'Day Spas',
        'Hair Salons',
        'Nail Salons',
        'Spa Services',
        'Tanning Salons',
    ],
    'Human Resources': [
        'Recruitment & Staffing Agencies',
        'Payroll & Benefits Administration',
        'Talent Management Systems',
        'Executive Search (Headhunting)',
        'Employee Training & Development',
        'HR Consulting',
        'Workforce Analytics',
        'Remote Work Solutions',
        'Background Checks',
        'Labor Law Compliance',
    ],
    'Information Technology (IT)': [
        'Enterprise Software (ERP, CRM)',
        'IT Consulting & System Integration',
        'Managed IT Services (MSP)',
        'Cloud Services (IaaS, PaaS, SaaS)',
        'Data Centers & Colocation',
        'Technical Support & Help Desk',
        'Legacy System Modernization',
        'Application Development',
        'IT Infrastructure & Networking',
        'Disaster Recovery Services',
    ],
    'Insurance': [
        'Life Insurance',
        'Health Insurance',
        'Property & Casualty (P&C)',
        'Auto Insurance',
        'Reinsurance',
        'Marine & Cargo Insurance',
        'Travel Insurance',
        'Pet Insurance',
        'Cyber Liability Insurance',
        'Title Insurance',
    ],
    'Legal & Law Firms': [
        'Corporate & Commercial Law',
        'Criminal Defense',
        'Family & Divorce Law',
        'Personal Injury & Accident',
        'Intellectual Property (IP) Law',
        'Employment & Labor Law',
        'Real Estate & Property Law',
        'Tax Law',
        'Immigration Law',
        'Environmental Law',
        'General Practice Law',
        'Real Estate Law',
        'Personal Injury Law',
        'Family Law',
        'Small Business Legal Services',
    ],
    'Logistics & Supply Chain': [
        'Freight Transportation (Truck, Rail, Air)',
        'Maritime Shipping',
        'Third-Party Logistics (3PL)',
        'Supply Chain Management Consulting',
        'Cold Chain Logistics',
        'Courier & Parcel Delivery',
        'Warehousing & Distribution',
        'Cargo Inspection',
        'Reverse Logistics (Returns)',
        'Inventory Management Systems',
    ],
    'Manufacturing (General)': [
        'Metal Fabrication',
        'Plastics & Rubber Molding',
        'CNC Machining',
        'Assembly & Contract Manufacturing',
        'Printing & Packaging',
        'Woodworking & Furniture',
        'Heavy Machinery Production',
        'Textile Mills',
        'Glass Production',
        'Additive Manufacturing (3D Printing)',
        'Appliance Repair',
        'Electronics Repair',
        'Furniture Refinishing',
    ],
    'Marketing & Advertising': [
        'Digital Marketing (SEO, PPC)',
        'Traditional Media (TV, Print, Radio)',
        'Social Media Marketing',
        'Creative Agencies (Design, Copywriting)',
        'Market Research & Analytics',
        'Public Relations (PR)',
        'Influencer Marketing',
        'Event Sponsorship',
        'Direct Mail Marketing',
        'Brand Strategy Consulting',
    ],
    'Media & Entertainment': [
        'Streaming Entertainment (OTT)',
        'Broadcasting (TV, Radio)',
        'Print Media (Newspapers, Magazines)',
        'Digital News Platforms',
        'Podcast Production',
        'Music Production & Labels',
        'Talent Agencies',
        'Book Publishing',
        'Outdoor Advertising (Billboards)',
        'Cable Television Networks',
    ],
    'Medical Devices': [
        'Diagnostic Imaging (MRI, CT, X-Ray)',
        'Surgical Instruments & Robotics',
        'Wearable Health Monitors',
        'Orthopedic Implants (Knees, Hips)',
        'Cardiovascular Devices (Stents, Pacemakers)',
        'Dental Equipment & Supplies',
        'In-vitro Diagnostics (IVD)',
        'Home Healthcare Devices',
        'Vision Care (Lenses, Lasers)',
        'Drug Delivery Systems (Pens, Pumps)',
    ],
    'Metals & Mining': [
        'Precious Metals (Gold, Silver, Platinum)',
        'Base Metals (Copper, Iron, Zinc)',
        'Coal Mining',
        'Uranium Mining',
        'Rare Earth Elements',
        'Aluminum Production',
        'Steel Manufacturing',
        'Mineral Exploration',
        'Mine Safety Equipment',
        'Smelting & Refining',
    ],
    'Non-Profit & NGOs': [
        'Humanitarian Relief',
        'Environmental Conservation',
        'Medical Research Foundations',
        'Educational Charities',
        'Animal Welfare',
        'Human Rights Advocacy',
        'Community Development',
        'Religious Organizations',
        'Arts & Culture Foundations',
        'Think Tanks (Policy Research)',
    ],
    'Oil & Gas': [
        'Upstream (Exploration, Drilling)',
        'Midstream (Pipelines, Storage)',
        'Downstream (Refining, Marketing)',
        'Liquefied Natural Gas (LNG)',
        'Oilfield Services (Rig Operations)',
        'Fuel Retail (Gas Stations)',
        'Lubricants & Greases',
        'Asphalt & Bitumen',
        'Natural Gas Processing',
        'Petrochemical Feedstocks',
    ],
    'Pharmaceuticals': [
        'Drug Research & Development (R&D)',
        'Generic Drug Manufacturing',
        'Over-the-Counter (OTC) Drugs',
        'Vaccines & Biologics',
        'Active Pharmaceutical Ingredients (API)',
        'Clinical Trial Services',
        'Medical Cannabis/CBD',
        'Veterinary Pharmaceuticals',
        'Drug Distribution (Wholesale)',
        'Regulatory Affairs (FDA)',
    ],
    'Real Estate & Property': [
        'Residential Real Estate (Homes, Condos)',
        'Commercial Real Estate (Office, Retail)',
        'Industrial Real Estate (Warehouses)',
        'Land Development',
        'Property Management',
        'Real Estate Investment Trusts (REITs)',
        'Real Estate Brokerage',
        'Appraisal & Valuation',
        'Luxury Estates',
        'Affordable Housing',
        'Residential Real Estate Brokers',
        'Property Managers',
        'Real Estate Appraisal',
        'Leasing Services',
    ],
    'Retail (Brick & Mortar)': [
        'Department Stores',
        'Supermarkets & Grocery',
        'Specialty Retail (Shoes, Electronics)',
        'Convenience Stores',
        "Warehouse Clubs (Costco/Sam's)",
        'Pharmacies & Drugstores',
        'Luxury Boutiques',
        'Home Improvement (DIY)',
        'Pet Stores',
        'Pop-up Shops',
    ],
    'Robotics & Automation': [
        'Industrial Robots (Welding, Assembly)',
        'Service Robots (Cleaning, Delivery)',
        'Collaborative Robots (Cobots)',
        'Autonomous Mobile Robots (AMRs)',
        'Drone Technology',
        'Robotic Process Automation (RPA - Software)',
        'Humanoid Robotics',
        'Medical/Surgical Robotics',
        'Defense & Security Robots',
        'Robotic Sensors & Vision',
    ],
    'Semiconductors': [
        'Chip Design (Fabless)',
        'Semiconductor Manufacturing (Foundries)',
        'Memory Chips (DRAM, NAND)',
        'Microprocessors (CPU, GPU)',
        'Analog & Mixed-Signal Chips',
        'Power Semiconductors',
        'Semiconductor Equipment (Lithography)',
        'Packaging & Testing',
        'IoT Chips',
        'Automotive Chips',
    ],
    'Social Media & Internet': [
        'Social Networking Platforms',
        'Messaging & Communication Apps',
        'Content Curation (News Aggregators)',
        'Forums & Community Platforms',
        'Dating Apps',
        'Social Media Management Tools',
        'User-Generated Content Platforms',
        'Viral Marketing Platforms',
        'Social Audio (Podcasts, Live Rooms)',
        'Review & Recommendation Sites',
    ],
    'Software (SaaS & Enterprise)': [
        'Customer Relationship Management (CRM)',
        'Enterprise Resource Planning (ERP)',
        'Project Management Software',
        'Communication & Collaboration Tools',
        'Human Capital Management (HCM)',
        'Business Intelligence (BI)',
        'Accounting & Financial Software',
        'Cybersecurity Software',
        'Supply Chain Software',
        'Legal Tech Software',
    ],
    'Sports & Athletics': [
        'Professional Sports Leagues (NBA, EPL)',
        'Sports Equipment Manufacturing',
        'Fantasy Sports Platforms',
        'Sports Betting/Gambling',
        'Collegiate Athletics',
        'Fitness Centers & Gyms',
        'Sports Apparel & Merchandising',
        'Sports Marketing/Sponsorship',
        'Coaching & Training Academies',
        'Outdoor Recreation (Camping, Fishing)',
        'Personal Trainers & Gyms',
        'Personal Training',
        'Yoga Studios',
        'Gyms & Fitness Centers',
    ],
    'Staffing & Recruitment': [
        'Temporary/Contract Staffing',
        'Permanent Placement',
        'Executive Search',
        'IT/Technical Recruitment',
        'Healthcare/Medical Staffing',
        'Industrial/Light Industrial Staffing',
        'Finance & Accounting Recruitment',
        'Remote/Virtual Staffing',
        'Payroll Services',
        'RPO (Recruitment Process Outsourcing)',
    ],
    'Telecommunications': [
        'Wireless/Mobile Network Operators',
        'Fixed-Line/Broadband Providers',
        'Fiber Optics Infrastructure',
        'Satellite Communications',
        'VoIP & Unified Communications',
        'Data Center Connectivity',
        '5G Rollout & Technology',
        'Telecom Equipment (Routers, Switches)',
        'Roaming Services',
        'Internet Exchange Points (IXPs)',
    ],
    'Tourism & Travel': [
        'Tour Operators (Package Tours)',
        'Travel Agencies (Online & Offline)',
        'Cruise Lines',
        'Car Rentals',
        'Tourist Attractions & Theme Parks',
        'Adventure Travel',
        'Cultural/Heritage Tourism',
        'Medical Tourism',
        'Travel Insurance',
        'Destination Marketing (Tourism Boards)',
    ],
    'Transportation': [
        'Public Transit (Buses, Subways)',
        'Trucking & Freight',
        'Rail Transport (Passenger & Cargo)',
        'Ride-Sharing & Taxis',
        'Logistics & Courier Services',
        'Bicycle & Micromobility (Scooters)',
        'Ferry & Water Transport',
        'Pipeline Transport',
        'Limousine & Chauffeur Services',
        'Parking & Toll Management',
        'Moving & Hauling Services',
        'Towing & Recovery Services',
        'Roadside Assistance',
        'Vehicle Transport',
    ],
    'Venture Capital & Private Equity': [
        'Early-Stage (Seed) VC',
        'Growth Equity',
        'Late-Stage VC',
        'Buyout PE (LBOs)',
        'Distressed Asset Investing',
        'Real Estate PE',
        'Fund of Funds',
        'Angel Investing Networks',
        'Corporate Venture Capital (CVC)',
        'Secondary Market Investments',
    ],
    'Waste Management': [
        'Municipal Solid Waste Collection',
        'Recycling (Plastic, Metal, Paper)',
        'Hazardous Waste Disposal',
        'Composting & Organic Waste',
        'Landfill Operations',
        'Waste-to-Energy Plants',
        'E-Waste Recycling',
        'Medical Waste Disposal',
        'Construction Debris Removal',
        'Chemical Waste Treatment',
    ],
    'Wholesale & Distribution': [
        'Grocery Wholesale',
        'Electronic Components Distribution',
        'Medical Supply Distribution',
        'Industrial Parts Wholesale',
        'Beverage Wholesale',
        'Tobacco & Cigarette Distribution',
        'Building Material Wholesale',
        'Automotive Parts Distribution',
        'Apparel Wholesale',
        'Pharmaceutical Wholesale',
    ],
    'Automotive Services': [
        'Auto Mechanics',
        'Towing & Roadside Assistance',
        'Vehicle Detailing',
    ],
    'Local Services & Trades': [
        'Pet Grooming',
        'Personal Chef & Catering',
        'Event Planning',
        'Pool Maintenance',
        'Mobile Detailing',
        'Moving & Hauling',
        'Catering',
        'Private Investigators',
        'Wedding Officiants',
        'Notary Public',
        'Signage & Graphics',
    ],
}

KNOWLEDGE_DOMAINS = [
    "Sales & Business Development", "Marketing", "Product", "Finance",
    "Legal & Compliance", "Technology", "Operations", "Industry Research",
]

CONTENT_TYPES = [
    "Document", "Video", "Music File", "Image File", "Software Code",
    "Audio/Podcast", "Spreadsheet", "Presentation",
]

# Lookup for content_contact_links.link_type_id — GSS-specific (TMS has no
# equivalent table; documents/content there has no per-record contact-link
# list).
CONTENT_LINK_TYPES = ["Author", "Reviewed By", "Approved By", "Point of Contact"]

# Full ISO 3166-1 alpha-2 list (minus 8 uninhabited territories) — see
# module docstring. (alpha-2 code, common name)
COUNTRIES = [
    ("AF", "Afghanistan"), ("AX", "Åland Islands"), ("AL", "Albania"),
    ("DZ", "Algeria"), ("AS", "American Samoa"), ("AD", "Andorra"),
    ("AO", "Angola"), ("AI", "Anguilla"), ("AG", "Antigua and Barbuda"),
    ("AR", "Argentina"), ("AM", "Armenia"), ("AW", "Aruba"),
    ("AU", "Australia"), ("AT", "Austria"), ("AZ", "Azerbaijan"),
    ("BS", "Bahamas"), ("BH", "Bahrain"), ("BD", "Bangladesh"),
    ("BB", "Barbados"), ("BY", "Belarus"), ("BE", "Belgium"),
    ("BZ", "Belize"), ("BJ", "Benin"), ("BM", "Bermuda"), ("BT", "Bhutan"),
    ("BO", "Bolivia"), ("BQ", "Bonaire, Sint Eustatius and Saba"),
    ("BA", "Bosnia and Herzegovina"), ("BW", "Botswana"), ("BR", "Brazil"),
    ("BN", "Brunei"), ("BG", "Bulgaria"), ("BF", "Burkina Faso"),
    ("BI", "Burundi"), ("CV", "Cabo Verde"), ("KH", "Cambodia"),
    ("CM", "Cameroon"), ("CA", "Canada"), ("KY", "Cayman Islands"),
    ("CF", "Central African Republic"), ("TD", "Chad"), ("CL", "Chile"),
    ("CN", "China"), ("CX", "Christmas Island"),
    ("CC", "Cocos (Keeling) Islands"), ("CO", "Colombia"),
    ("KM", "Comoros"), ("CD", "Congo (Democratic Republic of the)"),
    ("CG", "Congo"), ("CK", "Cook Islands"), ("CR", "Costa Rica"),
    ("CI", "Côte d'Ivoire"), ("HR", "Croatia"), ("CU", "Cuba"),
    ("CW", "Curaçao"), ("CY", "Cyprus"), ("CZ", "Czechia"),
    ("DK", "Denmark"), ("DJ", "Djibouti"), ("DM", "Dominica"),
    ("DO", "Dominican Republic"), ("EC", "Ecuador"), ("EG", "Egypt"),
    ("SV", "El Salvador"), ("GQ", "Equatorial Guinea"), ("ER", "Eritrea"),
    ("EE", "Estonia"), ("SZ", "Eswatini"), ("ET", "Ethiopia"),
    ("FK", "Falkland Islands"), ("FO", "Faroe Islands"), ("FJ", "Fiji"),
    ("FI", "Finland"), ("FR", "France"), ("GF", "French Guiana"),
    ("PF", "French Polynesia"), ("GA", "Gabon"), ("GM", "Gambia"),
    ("GE", "Georgia"), ("DE", "Germany"), ("GH", "Ghana"),
    ("GI", "Gibraltar"), ("GR", "Greece"), ("GL", "Greenland"),
    ("GD", "Grenada"), ("GP", "Guadeloupe"), ("GU", "Guam"),
    ("GT", "Guatemala"), ("GG", "Guernsey"), ("GN", "Guinea"),
    ("GW", "Guinea-Bissau"), ("GY", "Guyana"), ("HT", "Haiti"),
    ("VA", "Vatican City"), ("HN", "Honduras"), ("HK", "Hong Kong"),
    ("HU", "Hungary"), ("IS", "Iceland"), ("IN", "India"),
    ("ID", "Indonesia"), ("IR", "Iran"), ("IQ", "Iraq"), ("IE", "Ireland"),
    ("IM", "Isle of Man"), ("IL", "Israel"), ("IT", "Italy"),
    ("JM", "Jamaica"), ("JP", "Japan"), ("JE", "Jersey"), ("JO", "Jordan"),
    ("KZ", "Kazakhstan"), ("KE", "Kenya"), ("KI", "Kiribati"),
    ("KP", "North Korea"), ("KR", "South Korea"), ("KW", "Kuwait"),
    ("KG", "Kyrgyzstan"), ("LA", "Laos"), ("LV", "Latvia"),
    ("LB", "Lebanon"), ("LS", "Lesotho"), ("LR", "Liberia"), ("LY", "Libya"),
    ("LI", "Liechtenstein"), ("LT", "Lithuania"), ("LU", "Luxembourg"),
    ("MO", "Macao"), ("MK", "North Macedonia"), ("MG", "Madagascar"),
    ("MW", "Malawi"), ("MY", "Malaysia"), ("MV", "Maldives"),
    ("ML", "Mali"), ("MT", "Malta"), ("MH", "Marshall Islands"),
    ("MQ", "Martinique"), ("MR", "Mauritania"), ("MU", "Mauritius"),
    ("YT", "Mayotte"), ("MX", "Mexico"), ("FM", "Micronesia"),
    ("MD", "Moldova"), ("MC", "Monaco"), ("MN", "Mongolia"),
    ("ME", "Montenegro"), ("MS", "Montserrat"), ("MA", "Morocco"),
    ("MZ", "Mozambique"), ("MM", "Myanmar"), ("NA", "Namibia"),
    ("NR", "Nauru"), ("NP", "Nepal"), ("NL", "Netherlands"),
    ("NC", "New Caledonia"), ("NZ", "New Zealand"), ("NI", "Nicaragua"),
    ("NE", "Niger"), ("NG", "Nigeria"), ("NU", "Niue"),
    ("NF", "Norfolk Island"), ("MP", "Northern Mariana Islands"),
    ("NO", "Norway"), ("OM", "Oman"), ("PK", "Pakistan"), ("PW", "Palau"),
    ("PS", "Palestine"), ("PA", "Panama"), ("PG", "Papua New Guinea"),
    ("PY", "Paraguay"), ("PE", "Peru"), ("PH", "Philippines"),
    ("PN", "Pitcairn"), ("PL", "Poland"), ("PT", "Portugal"),
    ("PR", "Puerto Rico"), ("QA", "Qatar"), ("RE", "Réunion"),
    ("RO", "Romania"), ("RU", "Russia"), ("RW", "Rwanda"),
    ("BL", "Saint Barthélemy"),
    ("SH", "Saint Helena, Ascension and Tristan da Cunha"),
    ("KN", "Saint Kitts and Nevis"), ("LC", "Saint Lucia"),
    ("MF", "Saint Martin"), ("PM", "Saint Pierre and Miquelon"),
    ("VC", "Saint Vincent and the Grenadines"), ("WS", "Samoa"),
    ("SM", "San Marino"), ("ST", "Sao Tome and Principe"),
    ("SA", "Saudi Arabia"), ("SN", "Senegal"), ("RS", "Serbia"),
    ("SC", "Seychelles"), ("SL", "Sierra Leone"), ("SG", "Singapore"),
    ("SX", "Sint Maarten"), ("SK", "Slovakia"), ("SI", "Slovenia"),
    ("SB", "Solomon Islands"), ("SO", "Somalia"), ("ZA", "South Africa"),
    ("SS", "South Sudan"), ("ES", "Spain"), ("LK", "Sri Lanka"),
    ("SD", "Sudan"), ("SR", "Suriname"), ("SE", "Sweden"),
    ("CH", "Switzerland"), ("SY", "Syria"), ("TW", "Taiwan"),
    ("TJ", "Tajikistan"), ("TZ", "Tanzania"), ("TH", "Thailand"),
    ("TL", "Timor-Leste"), ("TG", "Togo"), ("TK", "Tokelau"),
    ("TO", "Tonga"), ("TT", "Trinidad and Tobago"), ("TN", "Tunisia"),
    ("TR", "Türkiye"), ("TM", "Turkmenistan"),
    ("TC", "Turks and Caicos Islands"), ("TV", "Tuvalu"), ("UG", "Uganda"),
    ("UA", "Ukraine"), ("AE", "United Arab Emirates"),
    ("GB", "United Kingdom"), ("US", "United States"), ("UY", "Uruguay"),
    ("UZ", "Uzbekistan"), ("VU", "Vanuatu"), ("VE", "Venezuela"),
    ("VN", "Vietnam"), ("VG", "British Virgin Islands"),
    ("VI", "U.S. Virgin Islands"), ("WF", "Wallis and Futuna"),
    ("EH", "Western Sahara"), ("YE", "Yemen"), ("ZM", "Zambia"),
    ("ZW", "Zimbabwe"),
]

# (code, full name) — label is always the full name, never just the code.
US_STATES = [
    ("AL", "Alabama"), ("AK", "Alaska"), ("AZ", "Arizona"), ("AR", "Arkansas"),
    ("CA", "California"), ("CO", "Colorado"), ("CT", "Connecticut"), ("DE", "Delaware"),
    ("FL", "Florida"), ("GA", "Georgia"), ("HI", "Hawaii"), ("ID", "Idaho"),
    ("IL", "Illinois"), ("IN", "Indiana"), ("IA", "Iowa"), ("KS", "Kansas"),
    ("KY", "Kentucky"), ("LA", "Louisiana"), ("ME", "Maine"), ("MD", "Maryland"),
    ("MA", "Massachusetts"), ("MI", "Michigan"), ("MN", "Minnesota"), ("MS", "Mississippi"),
    ("MO", "Missouri"), ("MT", "Montana"), ("NE", "Nebraska"), ("NV", "Nevada"),
    ("NH", "New Hampshire"), ("NJ", "New Jersey"), ("NM", "New Mexico"), ("NY", "New York"),
    ("NC", "North Carolina"), ("ND", "North Dakota"), ("OH", "Ohio"), ("OK", "Oklahoma"),
    ("OR", "Oregon"), ("PA", "Pennsylvania"), ("RI", "Rhode Island"), ("SC", "South Carolina"),
    ("SD", "South Dakota"), ("TN", "Tennessee"), ("TX", "Texas"), ("UT", "Utah"),
    ("VT", "Vermont"), ("VA", "Virginia"), ("WA", "Washington"), ("WV", "West Virginia"),
    ("WI", "Wisconsin"), ("WY", "Wyoming"), ("DC", "District of Columbia"),
]

# US cities with population over ~15,000 (3,405 places across all 50 states
# + DC), sourced from the GeoNames gazetteer via the geonamescache PyPI
# package (GeoNames data, CC BY 4.0 — https://www.geonames.org/). Keyed by
# US_STATES postal code; fed through _seed_cities() below in
# seed_global_lookups(). No population is stored (cities has no such
# column) — this list only decides which real place names are worth
# offering in the City picker.
US_CITIES = {
    "AK": [
        'Anchorage', 'Badger', 'Eagle River', 'Fairbanks', 'Juneau',
    ],
    "AL": [
        'Alabaster', 'Albertville', 'Anniston', 'Athens', 'Auburn', 'Bessemer', 'Birmingham',
        'Center Point', 'Cullman', 'Daphne', 'Decatur', 'Dixiana', 'Dothan', 'East Florence',
        'Enterprise', 'Fairhope', 'Florence', 'Foley', 'Gadsden', 'Helena', 'Homewood',
        'Hoover', 'Hueytown', 'Huntsville', 'Madison', 'Millbrook', 'Mobile', 'Montgomery',
        'Mountain Brook', 'Northport', 'Opelika', 'Oxford', 'Pelham', 'Phenix City',
        'Prattville', 'Prichard', 'Selma', 'Talladega', 'Tillmans Corner', 'Troy',
        'Trussville', 'Tuscaloosa', 'Vestavia Hills',
    ],
    "AR": [
        'Bella Vista', 'Benton', 'Bentonville', 'Bryant', 'Cabot', 'Conway', 'El Dorado',
        'Fayetteville', 'Fort Smith', 'Hot Springs', 'Jacksonville', 'Jonesboro',
        'Little Rock', 'Maumelle', 'North Little Rock', 'Paragould', 'Pine Bluff', 'Rogers',
        'Russellville', 'Searcy', 'Sherwood', 'Siloam Springs', 'Springdale', 'Texarkana',
        'Van Buren', 'West Memphis',
    ],
    "AZ": [
        'Ahwatukee Foothills', 'Alhambra', 'Anthem', 'Apache Junction', 'Avondale', 'Buckeye',
        'Bullhead City', 'Casa Grande', 'Casas Adobes', 'Catalina Foothills', 'Central City',
        'Chandler', 'Deer Valley', 'Douglas', 'Drexel Heights', 'El Mirage', 'Eloy', 'Encanto',
        'Flagstaff', 'Florence', 'Flowing Wells', 'Fortuna Foothills', 'Fountain Hills',
        'Gilbert', 'Glendale', 'Goodyear', 'Green Valley', 'Kingman', 'Lake Havasu City',
        'Marana', 'Maricopa', 'Maryvale', 'Mesa', 'Nogales', 'Oro Valley', 'Payson', 'Peoria',
        'Phoenix', 'Prescott', 'Prescott Valley', 'Queen Creek', 'Rio Rico', 'Sahuarita',
        'San Luis', 'San Tan Valley', 'Scottsdale', 'Sierra Vista', 'Somerton', 'Sun City',
        'Sun City West', 'Surprise', 'Tanque Verde', 'Tempe', 'Tempe Junction', 'Tucson',
        'Yuma',
    ],
    "CA": [
        'Adelanto', 'Agoura', 'Agoura Hills', 'Agua Caliente', 'Alameda', 'Albany', 'Alhambra',
        'Aliso Viejo', 'Altadena', 'Alum Rock', 'American Canyon', 'Anaheim', 'Antelope',
        'Antioch', 'Apple Valley', 'Arcadia', 'Arcata', 'Arden-Arcade', 'Arroyo Grande',
        'Artesia', 'Arvin', 'Ashland', 'Atascadero', 'Atwater', 'Atwater Village',
        'Avocado Heights', 'Azusa', 'Bakersfield', 'Baldwin Park', 'Banning', 'Barstow',
        'Barstow Heights', 'Bay Point', 'Bayside', 'Bayview-Hunters Point', 'Beaumont', 'Bell',
        'Bell Gardens', 'Bellflower', 'Belmont', 'Benicia', 'Berkeley', 'Beverly Hills',
        'Bloomington', 'Blythe', 'Bostonia', 'Boyle Heights', 'Brawley', 'Brea', 'Brentwood',
        'Buena Park', 'Burbank', 'Burlingame', 'Calabasas', 'Calexico', 'Camarillo',
        'Cameron Park', 'Campbell', 'Canoga Park', 'Canyon Country', 'Carlsbad', 'Carmichael',
        'Carson', 'Casa de Oro-Mount Helix', 'Castaic', 'Castro Valley', 'Cathedral City',
        'Ceres', 'Cerritos', 'Chatsworth', 'Chico', 'Chinatown', 'Chino', 'Chino Hills',
        'Chowchilla', 'Chula Vista', 'Citrus Heights', 'Claremont', 'Clearlake', 'Clovis',
        'Coachella', 'Coalinga', 'Colton', 'Compton', 'Concord', 'Corcoran', 'Corona',
        'Coronado', 'Costa Mesa', 'Covina', 'Cudahy', 'Culver City', 'Cupertino', 'Cypress',
        'Daly City', 'Dana Point', 'Danville', 'Davis', 'Delano', 'Desert Hot Springs',
        'Diamond Bar', 'Dinuba', 'Dixon', 'Downey', 'Duarte', 'Dublin', 'East Hemet',
        'East Los Angeles', 'East Palo Alto', 'East Rancho Dominguez', 'Eastvale', 'Echo Park',
        'El Cajon', 'El Camino Real', 'El Centro', 'El Cerrito', 'El Dorado Hills', 'El Monte',
        'El Segundo', 'Elk Grove', 'Encinitas', 'Encino', 'Escondido', 'Eureka', 'Fair Oaks',
        'Fairfield', 'Fallbrook', 'Fillmore', 'Florence-Graham', 'Florin', 'Folsom', 'Fontana',
        'Foothill Farms', 'Foster City', 'Fountain Valley', 'Fremont', 'Fresno', 'Fullerton',
        'Galt', 'Garden Grove', 'Gardena', 'Gilroy', 'Glen Avon', 'Glendale', 'Glendora',
        'Goleta', 'Granite Bay', 'Greenfield', 'Hacienda Heights', 'Hanford', 'Hawthorne',
        'Hayward', 'Hemet', 'Hercules', 'Hermosa Beach', 'Hesperia', 'Highland', 'Hollister',
        'Hollywood', 'Huntington Beach', 'Huntington Park', 'Imperial', 'Imperial Beach',
        'Indio', 'Inglewood', 'Irvine', 'Isla Vista', 'Jurupa Valley', 'Koreatown',
        'La Cañada Flintridge', 'La Crescenta-Montrose', 'La Habra', 'La Jolla', 'La Mesa',
        'La Mirada', 'La Palma', 'La Presa', 'La Puente', 'La Quinta', 'La Verne',
        'Ladera Ranch', 'Lafayette', 'Laguna', 'Laguna Beach', 'Laguna Hills', 'Laguna Niguel',
        'Laguna Woods', 'Lake Elsinore', 'Lake Forest', 'Lakeside', 'Lakewood', 'Lamont',
        'Lancaster', 'Lathrop', 'Lawndale', 'Lemon Grove', 'Lemoore', 'Lennox', 'Lincoln',
        'Linda', 'Live Oak', 'Livermore', 'Lodi', 'Loma Linda', 'Lomita', 'Lompoc',
        'Long Beach', 'Los Altos', 'Los Angeles', 'Los Banos', 'Los Gatos', 'Lynwood',
        'Madera', 'Manhattan Beach', 'Manteca', 'Marina', 'Martinez', 'Maywood',
        'McKinleyville', 'Mead Valley', 'Menifee', 'Menlo Park', 'Merced', 'Mid-City',
        'Millbrae', 'Milpitas', 'Mira Mesa', 'Mission District', 'Mission Viejo', 'Modesto',
        'Monrovia', 'Montclair', 'Montebello', 'Monterey', 'Monterey Park', 'Moorpark',
        'Moraga', 'Moreno Valley', 'Morgan Hill', 'Mountain View', 'Murrieta', 'Napa',
        'National City', 'Newark', 'Newport Beach', 'Nipomo', 'Noe Valley', 'Norco',
        'North Highlands', 'North Hills', 'North Hollywood', 'North Tustin', 'Northridge',
        'Northwood', 'Norwalk', 'Novato', 'Oakdale', 'Oakland', 'Oakley', 'Oceanside',
        'Oildale', 'Ontario', 'Orange', 'Orangevale', 'Orcutt', 'Orinda', 'Oroville', 'Oxnard',
        'Pacific Grove', 'Pacific Palisades', 'Pacifica', 'Palm Desert', 'Palm Springs',
        'Palmdale', 'Palo Alto', 'Paradise', 'Paramount', 'Parkside', 'Parlier', 'Pasadena',
        'Paso Robles', 'Patterson', 'Perris', 'Petaluma', 'Pico Rivera', 'Pinole', 'Pittsburg',
        'Placentia', 'Pleasant Hill', 'Pleasanton', 'Pomona', 'Port Hueneme', 'Porterville',
        'Poway', 'Prunedale', 'Ramona', 'Rancho Cordova', 'Rancho Cucamonga', 'Rancho Mirage',
        'Rancho Palos Verdes', 'Rancho Penasquitos', 'Rancho San Diego',
        'Rancho Santa Margarita', 'Redding', 'Redlands', 'Redondo Beach', 'Redwood City',
        'Reedley', 'Reseda', 'Rialto', 'Richmond', 'Ridgecrest', 'Rio Linda', 'Ripon',
        'Riverbank', 'Riverside', 'Rocklin', 'Rohnert Park', 'Rosamond', 'Rosemead',
        'Rosemont', 'Roseville', 'Rowland Heights', 'Rubidoux', 'Sacramento', 'Salinas',
        'San Bernardino', 'San Bruno', 'San Carlos', 'San Clemente', 'San Diego', 'San Dimas',
        'San Fernando', 'San Francisco', 'San Gabriel', 'San Jacinto', 'San Jose',
        'San Juan Capistrano', 'San Leandro', 'San Lorenzo', 'San Luis Obispo', 'San Marcos',
        'San Mateo', 'San Pablo', 'San Pedro', 'San Rafael', 'San Ramon', 'Sanger',
        'Santa Ana', 'Santa Barbara', 'Santa Clara', 'Santa Clarita', 'Santa Cruz',
        'Santa Fe Springs', 'Santa Maria', 'Santa Monica', 'Santa Paula', 'Santa Rosa',
        'Santee', 'Saratoga', 'Sawtelle', 'Seal Beach', 'Seaside', 'Selma', 'Shafter',
        'Sherman Oaks', 'Silver Lake', 'Simi Valley', 'Soledad', 'South El Monte',
        'South Gate', 'South Lake Tahoe', 'South Pasadena', 'South San Francisco',
        'South San Jose Hills', 'South Whittier', 'South Yuba City', 'Spring Valley',
        'Stanton', 'Stevenson Ranch', 'Stockton', 'Stonegate', 'Studio City', 'Suisun',
        'Sun City', 'Sunland', 'Sunnyvale', 'Susanville', 'Sylmar', 'Temecula', 'Temple City',
        'Thousand Oaks', 'Torrance', 'Tracy', 'Truckee', 'Tujunga', 'Tulare', 'Turlock',
        'Tustin', 'Tustin Legacy', 'Twentynine Palms', 'UC Irvine', 'Ukiah', 'Union City',
        'Universal City', 'Upland', 'Vacaville', 'Valencia', 'Valinda', 'Vallejo',
        'Valley Glen', 'Van Nuys', 'Venice', 'Ventura', 'Vermont Square', 'Victorville',
        'Vincent', 'Vineyard', 'Visalia', 'Visitacion Valley', 'Vista', 'Walnut',
        'Walnut Creek', 'Walnut Park', 'Wasco', 'Watsonville', 'West Carson', 'West Covina',
        'West Hills', 'West Hollywood', 'West Puente Valley', 'West Sacramento',
        'West Whittier-Los Nietos', 'Westminster', 'Westmont', 'Westpark', 'Whittier',
        'Wildomar', 'Willowbrook', 'Wilmington', 'Windsor', 'Winnetka', 'Winter Gardens',
        'Woodbridge', 'Woodland', 'Woodland Hills', 'Yorba Linda', 'Yuba City', 'Yucaipa',
        'Yucca Valley',
    ],
    "CO": [
        'Arvada', 'Aurora', 'Boulder', 'Brighton', 'Broomfield', 'Castle Rock', 'Castlewood',
        'Cañon City', 'Centennial', 'Cimarron Hills', 'Clifton', 'Colorado Springs',
        'Columbine', 'Commerce City', 'Dakota Ridge', 'Denver', 'Durango', 'Englewood', 'Erie',
        'Evans', 'Fort Collins', 'Fountain', 'Golden', 'Grand Junction', 'Greeley',
        'Greenwood Village', 'Highlands Ranch', 'Ken Caryl', 'Lafayette', 'Lakewood',
        'Littleton', 'Longmont', 'Louisville', 'Loveland', 'Montrose', 'Northglenn', 'Parker',
        'Pueblo', 'Pueblo West', 'Security-Widefield', 'Sherrelwood', 'Southglenn', 'Thornton',
        'Westminster', 'Wheat Ridge', 'Windsor',
    ],
    "CT": [
        'Ansonia', 'Avon', 'Bloomfield', 'Branford', 'Bridgeport', 'Bristol', 'Cheshire',
        'City of Milford (balance)', 'Danbury', 'Darien', 'East Hartford', 'East Haven',
        'East Norwalk', 'Enfield', 'Fairfield', 'Farmington', 'Glastonbury', 'Guilford',
        'Hamden', 'Hartford', 'Killingly Center', 'Ledyard', 'Madison', 'Manchester',
        'Mansfield City', 'Meriden', 'Middletown', 'Milford', 'Montville Center', 'Naugatuck',
        'New Britain', 'New Canaan', 'New Haven', 'New London', 'Newington', 'North Haven',
        'North Stamford', 'Norwalk', 'Norwich', 'Plainfield', 'Plainville', 'Seymour',
        'Shelton', 'South Windsor', 'Southbury', 'Southington', 'Stamford', 'Storrs',
        'Stratford', 'Torrington', 'Trumbull', 'Wallingford', 'Wallingford Center',
        'Waterbury', 'Waterford', 'West Hartford', 'West Haven', 'West Torrington', 'Westport',
        'Wethersfield', 'Willimantic', 'Wilton', 'Windham', 'Windsor', 'Wolcott',
    ],
    "DC": [
        'Adams Morgan', 'Brightwood', 'Capitol Hill', 'Capitol Riverfront',
        'Central 14th Street / Spring Road', 'Columbia Heights', 'Downtown DC',
        'Dupont Circle', 'Foggy Bottom', 'Golden Triangle', 'H Street NE', 'Kennedy Street',
        'Mount Pleasant', 'Mount Vernon Triangle', 'NoMa', 'Northwest One', 'Park View',
        'Petworth', 'Pleasant Plains', 'Shaw', 'Southwest Waterfront', 'Washington',
    ],
    "DE": [
        'Bear', 'Dover', 'Middletown', 'Newark', 'Wilmington',
    ],
    "FL": [
        'Alafaya', 'Allapattah', 'Altamonte Springs', 'Apopka', 'Auburndale', 'Aventura',
        'Bartow', 'Bayonet Point', 'Bayshore Gardens', 'Belle Glade', 'Bellview',
        'Bloomingdale', 'Boca Del Mar', 'Boca Raton', 'Bonita Springs', 'Boynton Beach',
        'Bradenton', 'Brandon', 'Brent', 'Brownsville', 'Buenaventura Lakes', 'Cantonment',
        'Cape Coral', 'Carol City', 'Carrollwood', 'Carrollwood Village', 'Casselberry',
        'Citrus Park', 'Clearwater', 'Clermont', 'Cocoa', 'Coconut Creek', 'Coconut Grove',
        'Cooper City', 'Coral Gables', 'Coral Springs', 'Coral Terrace', 'Country Club',
        'Country Walk', 'Crestview', 'Cutler', 'Cutler Bay', 'Cutler Ridge', 'Dania Beach',
        'Davie', 'Daytona Beach', 'DeBary', 'DeLand', 'Deerfield Beach', 'Delray Beach',
        'Deltona', 'Doral', 'Dunedin', 'East Lake', 'East Lake-Orient Park', 'East Naples',
        'East Pensacola Heights', 'Edgewater', 'Egypt Lake-Leto', 'Eloise', 'Ensley', 'Estero',
        'Eustis', 'Ferry Pass', 'Flagami', 'Fleming Island', 'Florida Ridge',
        'Fort Lauderdale', 'Fort Myers', 'Fort Pierce', 'Fort Walton Beach', 'Fountainebleau',
        'Four Corners', 'Fruit Cove', 'Gainesville', 'Glenvar Heights', 'Golden Gate',
        'Golden Glades', 'Greater Northdale', 'Greenacres City', 'Haines City',
        'Hallandale Beach', 'Hialeah', 'Hialeah Gardens', 'Holiday', 'Hollywood', 'Homestead',
        'Immokalee', 'Iona', 'Ives Estates', 'Jacksonville', 'Jacksonville Beach',
        'Jasmine Estates', 'Jupiter', 'Kendale Lakes', 'Kendall', 'Kendall West', 'Key West',
        'Keystone', 'Kissimmee', 'Lake Butler', 'Lake Magdalene', 'Lake Mary', 'Lake Wales',
        'Lake Worth Beach', 'Lake Worth Corridor', 'Lakeland', 'Lakeside', "Land O' Lakes",
        'Largo', 'Lauderdale Lakes', 'Lauderhill', 'Lealman', 'Leesburg', 'Lehigh Acres',
        'Leisure City', 'Little Havana', 'Lutz', 'Lynn Haven', 'Maitland', 'Marco Island',
        'Margate', 'Marion Oaks', 'Meadow Woods', 'Melbourne', 'Merritt Island', 'Miami',
        'Miami Beach', 'Miami Gardens', 'Miami Lakes', 'Midway', 'Miramar', 'Myrtle Grove',
        'Naples', 'Navarre', 'New Port Richey', 'New Smyrna Beach', 'Norland',
        'North Fort Myers', 'North Lauderdale', 'North Miami', 'North Miami Beach',
        'North Port', 'Northdale', 'Oak Ridge', 'Oakland Park', 'Oakleaf Plantation', 'Ocala',
        'Ocoee', 'Ojus', 'Opa-locka', 'Orlando', 'Ormond Beach', 'Oviedo', 'Pace', 'Palm Bay',
        'Palm Beach Gardens', 'Palm City', 'Palm Coast', 'Palm Harbor', 'Palm River-Clair Mel',
        'Palm Springs', 'Palm Valley', 'Palmetto Bay', 'Panama City', 'Parkland',
        'Pembroke Pines', 'Pensacola', 'Pine Hills', 'Pinecrest', 'Pinellas Park', 'Pinewood',
        'Plant City', 'Plantation', 'Poinciana', 'Pompano Beach', 'Ponte Vedra Beach',
        'Port Charlotte', 'Port Orange', 'Port Saint Lucie', 'Princeton', 'Punta Gorda',
        'Punta Gorda Isles', 'Richmond West', 'Riverview', 'Riviera Beach', 'Rockledge',
        'Royal Palm Beach', 'Ruskin', 'Safety Harbor', 'Saint Cloud', 'San Carlos Park',
        'Sandalfoot Cove', 'Sanford', 'Santa Rosa Beach', 'Sarasota', 'Sebastian', 'Seminole',
        'South Bradenton', 'South Miami Heights', 'Southchase', 'Spring Hill', 'St. Johns',
        'St. Petersburg', 'Stuart', 'Sun City Center', 'Sunny Isles Beach', 'Sunrise',
        'Sunset', 'Sweetwater', 'Tallahassee', 'Tamarac', 'Tamiami', 'Tampa', 'Tarpon Springs',
        'Tavares', 'Temple Terrace', 'The Acreage', 'The Crossings', 'The Hammocks',
        'The Villages', 'Three Lakes', 'Titusville', "Town 'n' Country", 'University',
        'University Park', 'Valrico', 'Venice', 'Vero Beach', 'Vero Beach South',
        'Wekiwa Springs', 'Wellington', 'Wesley Chapel', 'West Hollywood', 'West Little River',
        'West Melbourne', 'West Palm Beach', 'West Park', 'West Pensacola',
        'West and East Lealman', 'Westchase', 'Westchester', 'Weston', 'Winter Garden',
        'Winter Haven', 'Winter Park', 'Winter Springs', 'Wright',
    ],
    "GA": [
        'Acworth', 'Albany', 'Alpharetta', 'Americus', 'Athens', 'Atlanta', 'Augusta',
        'Belvedere Park', 'Brookhaven', 'Brunswick', 'Calhoun', 'Candler-McAfee', 'Canton',
        'Carrollton', 'Cartersville', 'Chamblee', 'Columbus', 'Conyers', 'Dalton', 'Decatur',
        'Douglasville', 'Dublin', 'Duluth', 'Dunwoody', 'East Point', 'Evans', 'Fayetteville',
        'Forest Park', 'Gainesville', 'Griffin', 'Hinesville', 'Johns Creek', 'Kennesaw',
        'Kingsland', 'LaGrange', 'Lawrenceville', 'Lithia Springs', 'Mableton', 'Macon',
        'Marietta', 'Martinez', 'McDonough', 'Milledgeville', 'Milton', 'Newnan', 'Norcross',
        'North Decatur', 'North Druid Hills', 'Peachtree City', 'Peachtree Corners', 'Perry',
        'Pooler', 'Redan', 'Riverdale', 'Rome', 'Roswell', 'Sandy Springs', 'Savannah',
        'Smyrna', 'Snellville', 'South Fulton', 'St. Marys', 'Statesboro', 'Stockbridge',
        'Stonecrest', 'Sugar Hill', 'Suwanee', 'Thomasville', 'Tifton', 'Tucker', 'Union City',
        'Valdosta', 'Warner Robins', 'Wilmington Island', 'Winder', 'Woodstock',
    ],
    "HI": [
        'Airport', 'Ala Moana - Kakaʻako', 'Aliamanu / Salt Lakes / Foster Village',
        'Diamond Head / Kapahulu / Saint Louis Heights', 'East Honolulu', 'Hawai‘i Kai',
        'Hilo', 'Honolulu', 'Joint Base Pearl Harbor Hickam', 'Kahului', 'Kailua', 'Kaimukī',
        'Kalihi Valley', 'Kalihi-Palama', 'Kaneohe', 'Kapolei', 'Kapolei Villages',
        'Koolauloa', 'Kuliouou - Kalani Iki', 'Kīhei', 'Liliha - Kapalama', 'Makakilo',
        'Makakilo / Kapolei / Honokai Hale', 'Makakilo City', 'Makakilo-Makaīwa Hills-Kunia',
        'Makiki / Lower Punchbowl / Tantalus', 'Manoa', 'McCully - Moiliili', 'Mililani Mauka',
        'Mililani Mauka / Launani Valley', 'Mililani Town', 'Mō‘ili‘ili', 'Niu Valley',
        'Nuuanu - Punchbowl', 'Pearl City', 'Schofield Barracks', 'Schofield-Wheeler',
        'Wahiawā', 'Wahiawā-Whitmore', 'Waiau-Pacific Palisades', 'Waikīkī', 'Wailuku',
        'Waipahu', 'ʻEwa Beach-Iroquois Point', 'ʻEwa Gentry-West Loch', '‘Ewa Beach',
        '‘Ewa Gentry',
    ],
    "IA": [
        'Altoona', 'Ames', 'Ankeny', 'Bettendorf', 'Burlington', 'Cedar Falls', 'Cedar Rapids',
        'Clinton', 'Clive', 'Coralville', 'Council Bluffs', 'Davenport', 'Des Moines',
        'Dubuque', 'Fort Dodge', 'Indianola', 'Iowa City', 'Johnston', 'Marion',
        'Marshalltown', 'Mason City', 'Muscatine', 'Newton', 'North Liberty', 'Ottumwa',
        'Sioux City', 'Urbandale', 'Waterloo', 'Waukee', 'West Des Moines',
    ],
    "ID": [
        'Boise', 'Caldwell', "Coeur d'Alene", 'Conda', 'Eagle', 'Idaho Falls', 'Kuna',
        'Lewiston', 'Lewiston Orchards', 'Meridian', 'Moscow', 'Nampa', 'Pocatello',
        'Post Falls', 'Rexburg', 'Twin Falls',
    ],
    "IL": [
        'Addison', 'Albany Park', 'Algonquin', 'Alsip', 'Alton', 'Arlington Heights',
        'Ashburn', 'Auburn Gresham', 'Aurora', 'Avondale', 'Bartlett', 'Batavia', 'Belleville',
        'Bellwood', 'Belmont Cragin', 'Belvidere', 'Bensenville', 'Berwyn', 'Bloomingdale',
        'Bloomington', 'Blue Island', 'Bolingbrook', 'Bourbonnais', 'Bradley', 'Bridgeport',
        'Bridgeview', 'Brighton Park', 'Brookfield', 'Buffalo Grove', 'Burbank',
        'Calumet City', 'Carbondale', 'Carol Stream', 'Carpentersville', 'Cary', 'Champaign',
        'Charleston', 'Chatham', 'Chicago', 'Chicago Heights', 'Chicago Lawn', 'Chicago Loop',
        'Cicero', 'Collinsville', 'Country Club Hills', 'Crest Hill', 'Crystal Lake',
        'Danville', 'Darien', 'DeKalb', 'Decatur', 'Deerfield', 'Des Plaines', 'Dixon',
        'Dolton', 'Douglas', 'Downers Grove', 'East Garfield Park', 'East Moline',
        'East Peoria', 'East Saint Louis', 'Edgewater', 'Edwardsville', 'Elgin',
        'Elk Grove Village', 'Elmhurst', 'Elmwood Park', 'Englewood', 'Evanston',
        'Evergreen Park', 'Fairview Heights', 'Frankfort', 'Franklin Park', 'Freeport',
        'Gage Park', 'Galesburg', 'Geneva', 'Glen Ellyn', 'Glendale Heights', 'Glenview',
        'Godfrey', 'Goodings Grove', 'Grand Boulevard', 'Granite City', 'Grayslake',
        'Greater Grand Crossing', 'Gurnee', 'Hanover Park', 'Harvey', 'Highland Park',
        'Hinsdale', 'Hoffman Estates', 'Homer Glen', 'Homewood', 'Huntley', 'Hyde Park',
        'Irving Park', 'Jacksonville', 'Joliet', 'Kankakee', 'Kenwood', 'La Grange',
        'Lake Forest', 'Lake Zurich', 'Lake in the Hills', 'Lansing', 'Lemont', 'Libertyville',
        'Lincoln Park', 'Lincoln Square', 'Lisle', 'Lockport', 'Logan Square', 'Lombard',
        'Loves Park', 'Lower West Side', 'Machesney Park', 'Macomb', 'Marion', 'Matteson',
        'Mattoon', 'Maywood', 'McHenry', 'McKinley Park', 'Melrose Park', 'Mokena', 'Moline',
        'Montgomery', 'Morgan Park', 'Morton', 'Morton Grove', 'Mount Greenwood',
        'Mount Prospect', 'Mount Vernon', 'Mundelein', 'Naperville', 'Near North Side',
        'Near South Side', 'New City', 'New Lenox', 'Niles', 'Normal', 'North Aurora',
        'North Center', 'North Chicago', 'North Lawndale', 'North Peoria', 'Northbrook',
        "O'Fallon", 'Oak Forest', 'Oak Lawn', 'Oak Park', 'Orland Park', 'Oswego', 'Ottawa',
        'Palatine', 'Palos Hills', 'Park Forest', 'Park Ridge', 'Pekin', 'Peoria',
        'Plainfield', 'Portage Park', 'Prospect Heights', 'Quincy', 'Rock Island', 'Rockford',
        'Rogers Park', 'Rolling Meadows', 'Romeoville', 'Roselle', 'Round Lake',
        'Round Lake Beach', 'Schaumburg', 'Shorewood', 'Skokie', 'South Chicago',
        'South Elgin', 'South Holland', 'South Lawndale', 'South Shore', 'Springfield',
        'St. Charles', 'Sterling', 'Streamwood', 'Sycamore', 'Tinley Park', 'Upper Alton',
        'Uptown', 'Urbana', 'Vernon Hills', 'Villa Park', 'Wasco', 'Washington', 'Waukegan',
        'West Chicago', 'West Elsdon', 'West Englewood', 'West Garfield Park', 'West Lawn',
        'West Ridge', 'West Town', 'Westchester', 'Westmont', 'Wheaton', 'Wheeling',
        'Wilmette', 'Woodlawn', 'Woodridge', 'Woodstock', 'Yorkville', 'Zion',
    ],
    "IN": [
        'Anderson', 'Avon', 'Bloomington', 'Broad Ripple', 'Brownsburg', 'Carmel',
        'Clarksville', 'Columbus', 'Crawfordsville', 'Crown Point', 'Dyer', 'East Chicago',
        'Elkhart', 'Evansville', 'Fairfield Heights', 'Fishers', 'Fort Wayne', 'Frankfort',
        'Franklin', 'Gary', 'Goshen', 'Granger', 'Greenfield', 'Greenwood', 'Griffith',
        'Hammond', 'Highland', 'Hobart', 'Huntington', 'Indianapolis', 'Jasper',
        'Jeffersonville', 'Kokomo', 'La Porte', 'Lafayette', 'Lawrence', 'Lebanon',
        'Logansport', 'Marion', 'Merrillville', 'Michigan City', 'Mishawaka', 'Muncie',
        'Munster', 'New Albany', 'New Castle', 'New Haven', 'Noblesville', 'Plainfield',
        'Portage', 'Richmond', 'Schererville', 'Seymour', 'Shelbyville', 'South Bend',
        'Terre Haute', 'Valparaiso', 'Vincennes', 'West Lafayette', 'Westfield', 'Zionsville',
    ],
    "KS": [
        'Derby', 'Dodge City', 'Emporia', 'Garden City', 'Gardner', 'Great Bend', 'Hays',
        'Hutchinson', 'Junction City', 'Kansas City', 'Lawrence', 'Leavenworth', 'Leawood',
        'Lenexa', 'Liberal', 'Manhattan', 'Newton', 'Olathe', 'Overland Park', 'Pittsburg',
        'Prairie Village', 'Salina', 'Shawnee', 'Topeka', 'Wichita',
    ],
    "KY": [
        'Ashland', 'Bowling Green', 'Burlington', 'Covington', 'Danville', 'Elizabethtown',
        'Erlanger', 'Fern Creek', 'Florence', 'Fort Thomas', 'Frankfort', 'Georgetown',
        'Henderson', 'Highview', 'Hopkinsville', 'Independence', 'Jeffersontown', 'Lexington',
        'Lexington-Fayette', 'Louisville', 'Madisonville', 'Meads', 'Murray', 'Newburg',
        'Newport', 'Nicholasville', 'Okolona', 'Owensboro', 'Paducah', 'Pleasure Ridge Park',
        'Radcliff', 'Richmond', 'Saint Matthews', 'Shelbyville', 'Shively', 'Valley Station',
        'Winchester',
    ],
    "LA": [
        'Alexandria', 'Baton Rouge', 'Bayou Cane', 'Bossier City', 'Central', 'Chalmette',
        'Estelle', 'Gretna', 'Hammond', 'Harvey', 'Houma', 'Kenner', 'Lafayette',
        'Lake Charles', 'Laplace', 'Marrero', 'Metairie', 'Metairie Terrace', 'Monroe',
        'Natchitoches', 'New Iberia', 'New Orleans', 'Opelousas', 'Prairieville', 'Ruston',
        'Shenandoah', 'Shreveport', 'Slidell', 'Sulphur', 'Terrytown', 'Zachary',
    ],
    "MA": [
        'Abington', 'Acton', 'Agawam', 'Allston', 'Amesbury', 'Amherst', 'Amherst Center',
        'Arlington', 'Ashland', 'Ashmont', 'Attleboro', 'Auburn', 'Back Bay', 'Barnstable',
        'Belmont', 'Beverly', 'Beverly Cove', 'Billerica', 'Boston', 'Braintree', 'Brighton',
        'Brockton', 'Brookline', 'Burlington', 'Cambridge', 'Canton', 'Charlestown',
        'Chelmsford', 'Chelsea', 'Chestnut Hill', 'Chicopee', 'Concord', 'Danvers', 'Dedham',
        'Dorchester', 'Dracut', 'Duxbury', 'East Boston', 'East Longmeadow', 'Easthampton',
        'Easton', 'Everett', 'Fairhaven', 'Fall River', 'Fenway/Kenmore', 'Fitchburg',
        'Framingham', 'Framingham Center', 'Franklin', 'Gardner', 'Gloucester', 'Grafton',
        'Greenfield', 'Hanover', 'Haverhill', 'Holden', 'Holyoke', 'Hyde Park',
        'Jamaica Plain', 'Lawrence', 'Leominster', 'Lexington', 'Longmeadow', 'Lowell',
        'Ludlow', 'Lynn', 'Malden', 'Mansfield', 'Marblehead', 'Marlborough', 'Mattapan',
        'Medford', 'Melrose', 'Methuen', 'Middleborough', 'Milford', 'Milton', 'Mission Hill',
        'Natick', 'Needham', 'New Bedford', 'Newburyport', 'Newton', 'North Andover',
        'North Attleborough Center', 'North Chicopee', 'Northampton', 'Norton', 'Norwood',
        'Orient Heights', 'Palmer', 'Peabody', 'Pittsfield', 'Quincy', 'Randolph', 'Reading',
        'Revere', 'Rockland', 'Roslindale', 'Roxbury Crossing', 'Salem', 'Saugus',
        'Shrewsbury', 'Somerset', 'Somerville', 'South Boston', 'South Hadley',
        'South Peabody', 'Southbridge', 'Springfield', 'Stoneham', 'Stoughton', 'Sudbury',
        'Swansea', 'Taunton', 'Tewksbury', 'Wakefield', 'Waltham', 'Watertown', 'Wellesley',
        'West Roxbury', 'West Springfield', 'Westfield', 'Westford', 'Weymouth', 'Wilmington',
        'Winchester', 'Winthrop', 'Woburn', 'Worcester', 'Yarmouth',
    ],
    "MD": [
        'Aberdeen', 'Adelphi', 'Annapolis', 'Arbutus', 'Arnold', 'Aspen Hill',
        'Ballenger Creek', 'Baltimore', 'Bel Air North', 'Bel Air South', 'Beltsville',
        'Bethesda', 'Bowie', 'Calverton', 'Camp Springs', 'Carney', 'Catonsville', 'Chillum',
        'Clinton', 'Cloverly', 'Cockeysville', 'College Park', 'Columbia', 'Crofton',
        'Cumberland', 'Damascus', 'Dundalk', 'East Riverdale', 'Easton', 'Edgewood',
        'Eldersburg', 'Elkridge', 'Elkton', 'Ellicott City', 'Essex', 'Fairland', 'Ferndale',
        'Fort Washington', 'Frankford', 'Frederick', 'Gaithersburg', 'Germantown',
        'Glassmanor', 'Glen Burnie', 'Greater Upper Marlboro', 'Green Haven', 'Greenbelt',
        'Gwynn Oak', 'Hagerstown', 'Hanover', 'Hillcrest Heights', 'Hunt Valley',
        'Hyattsville', 'Ilchester', 'Lake Shore', 'Landover', 'Langley Park',
        'Lanham-Seabrook', 'Laurel', 'Lochearn', 'Lutherville-Timonium', 'Maryland City',
        'Middle River', 'Milford Mill', 'Montgomery Village', 'North Bel Air',
        'North Bethesda', 'North Potomac', 'Odenton', 'Olney', 'Owings Mills', 'Oxon Hill',
        'Oxon Hill-Glassmanor', 'Parkville', 'Parole', 'Pasadena', 'Perry Hall', 'Pikesville',
        'Potomac', 'Randallstown', 'Redland', 'Reisterstown', 'Rockville', 'Rosedale',
        'Rossville', 'Saint Charles', 'Salisbury', 'Scaggsville', 'Seabrook', 'Severn',
        'Severna Park', 'Silver Spring', 'South Bel Air', 'South Gate', 'South Laurel',
        'St. Charles', 'Suitland', 'Suitland-Silver Hill', 'Takoma Park', 'Towson', 'Waldorf',
        'West Elkridge', 'Westminster', 'Wheaton', 'White Oak', 'Woodlawn',
    ],
    "ME": [
        'Auburn', 'Augusta', 'Bangor', 'Biddeford', 'Brunswick', 'Lewiston', 'Portland',
        'Saco', 'Sanford', 'South Portland', 'South Portland Gardens', 'Waterville',
        'West Scarborough', 'Westbrook',
    ],
    "MI": [
        'Adrian', 'Allen Park', 'Allendale', 'Ann Arbor', 'Auburn Hills', 'Battle Creek',
        'Bay City', 'Berkley', 'Birmingham', 'Burton', 'Canton', 'Clinton Township',
        'Dearborn', 'Dearborn Heights', 'Detroit', 'East Lansing', 'Eastpointe',
        'Farmington Hills', 'Ferndale', 'Flint', 'Forest Hills', 'Garden City', 'Grand Rapids',
        'Grandville', 'Grosse Pointe Woods', 'Hamtramck', 'Haslett', 'Hazel Park', 'Holland',
        'Holt', 'Inkster', 'Jackson', 'Jenison', 'Kalamazoo', 'Kentwood', 'Lansing',
        'Lincoln Park', 'Livonia', 'Madison Heights', 'Marquette', 'Midland', 'Monroe',
        'Mount Clemens', 'Mount Pleasant', 'Muskegon', 'Norton Shores', 'Novi', 'Oak Park',
        'Okemos', 'Pontiac', 'Port Huron', 'Portage', 'Redford', 'Rochester Hills', 'Romulus',
        'Roseville', 'Royal Oak', 'Saginaw', 'Saginaw Township North', 'Saint Clair Shores',
        'Shelby', 'Southfield', 'Southgate', 'Sterling Heights', 'Taylor', 'Traverse City',
        'Trenton', 'Troy', 'Walker', 'Warren', 'Waterford', 'Waverly', 'Wayne',
        'West Bloomfield Township', 'Westland', 'Wyandotte', 'Wyoming', 'Ypsilanti',
    ],
    "MN": [
        'Albert Lea', 'Andover', 'Anoka', 'Apple Valley', 'Austin', 'Blaine', 'Bloomington',
        'Brooklyn Center', 'Brooklyn Park', 'Buffalo', 'Burnsville', 'Champlin', 'Chanhassen',
        'Chaska', 'Columbia Heights', 'Coon Rapids', 'Cottage Grove', 'Crystal', 'Duluth',
        'Eagan', 'Eden Prairie', 'Edina', 'Elk River', 'Faribault', 'Farmington',
        'Forest Lake', 'Fridley', 'Golden Valley', 'Ham Lake', 'Hastings', 'Hibbing',
        'Hopkins', 'Inver Grove Heights', 'Lakeville', 'Lino Lakes', 'Longfellow Community',
        'Mankato', 'Maple Grove', 'Maplewood', 'Minneapolis', 'Minnetonka', 'Minnetonka Mills',
        'Moorhead', 'New Brighton', 'New Hope', 'Northfield', 'Oakdale', 'Otsego', 'Owatonna',
        'Plymouth', 'Prior Lake', 'Ramsey', 'Red Wing', 'Richfield', 'Rochester', 'Rosemount',
        'Roseville', 'Saint Cloud', 'Saint Louis Park', 'Saint Michael', 'Saint Paul',
        'Sartell', 'Savage', 'Shakopee', 'Shoreview', 'South Saint Paul', 'Stillwater',
        'West Coon Rapids', 'West Saint Paul', 'White Bear Lake', 'Willmar', 'Winona',
        'Woodbury',
    ],
    "MO": [
        'Affton', 'Arnold', 'Ballwin', 'Belton', 'Blue Springs', 'Cape Girardeau',
        'Chesterfield', 'Clayton', 'Columbia', 'Concord', 'Creve Coeur', 'East Independence',
        'Farmington', 'Ferguson', 'Florissant', 'Fort Leonard Wood', 'Gladstone', 'Grandview',
        'Hannibal', 'Hazelwood', 'Independence', 'Jefferson City', 'Joplin', 'Kansas City',
        'Kirksville', 'Kirkwood', "Lee's Summit", 'Lemay', 'Liberty', 'Manchester',
        'Maryland Heights', 'Mehlville', 'Nixa', "O'Fallon", 'Oakville', 'Old Jamestown',
        'Overland', 'Ozark', 'Poplar Bluff', 'Raymore', 'Raytown', 'Republic', 'Rolla',
        'Saint Charles', 'Saint Joseph', 'Saint Peters', 'Sedalia', 'Sikeston', 'Spanish Lake',
        'Springfield', 'St. Louis', 'University City', 'Warrensburg', 'Webster Groves',
        'Wentzville', 'Wildwood',
    ],
    "MS": [
        'Biloxi', 'Brandon', 'Clarksdale', 'Clinton', 'Columbus', 'Gautier', 'Greenville',
        'Greenwood', 'Gulfport', 'Hattiesburg', 'Hernando', 'Horn Lake', 'Jackson', 'Laurel',
        'Long Beach', 'Madison', 'Meridian', 'Natchez', 'Ocean Springs', 'Olive Branch',
        'Oxford', 'Pascagoula', 'Pearl', 'Ridgeland', 'Southaven', 'Starkville', 'Tupelo',
        'Vicksburg', 'West Gulfport',
    ],
    "MT": [
        'Billings', 'Bozeman', 'Butte', 'Great Falls', 'Helena', 'Kalispell', 'Missoula',
    ],
    "NC": [
        'Albemarle', 'Apex', 'Asheboro', 'Asheville', 'Boone', 'Burlington', 'Carrboro',
        'Cary', 'Chapel Hill', 'Charlotte', 'Clayton', 'Clemmons', 'Concord', 'Cornelius',
        'Durham', 'Eden', 'Elizabeth City', 'Fayetteville', 'Fort Bragg', 'Fuquay-Varina',
        'Garner', 'Gastonia', 'Goldsboro', 'Greensboro', 'Greenville', 'Havelock', 'Henderson',
        'Hickory', 'High Point', 'Holly Springs', 'Hope Mills', 'Huntersville', 'Indian Trail',
        'Jacksonville', 'Kannapolis', 'Kernersville', 'Kinston', 'Laurinburg', 'Leland',
        'Lenoir', 'Lexington', 'Lumberton', 'Matthews', 'Mint Hill', 'Monroe', 'Mooresville',
        'Morganton', 'Morrisville', 'New Bern', 'Pinehurst', 'Raleigh', 'Roanoke Rapids',
        'Rocky Mount', 'Salisbury', 'Sanford', 'Shelby', 'Stallings', 'Statesville',
        'Thomasville', 'Wake Forest', 'West Raleigh', 'Wilmington', 'Wilson', 'Winston-Salem',
    ],
    "ND": [
        'Bismarck', 'Dickinson', 'Fargo', 'Grand Forks', 'Jamestown', 'Mandan', 'Minot',
        'West Fargo', 'Williston',
    ],
    "NE": [
        'Bellevue', 'Columbus', 'Fremont', 'Grand Island', 'Hastings', 'Kearney', 'La Vista',
        'Lincoln', 'Norfolk', 'North Platte', 'Omaha', 'Papillion',
    ],
    "NH": [
        'Bedford', 'Concord', 'Derry', 'Derry Village', 'Dover', 'East Concord', 'Keene',
        'Laconia', 'Manchester', 'Merrimack', 'Nashua', 'Portsmouth', 'Rochester', 'Salem',
    ],
    "NJ": [
        'Asbury Park', 'Atlantic City', 'Avenel', 'Basking Ridge', 'Bayonne', 'Bayville',
        'Belleville', 'Bergenfield', 'Bloomfield', 'Brick', 'Bridgeton', 'Bridgewater',
        'Camden', 'Carteret', 'Cherry Hill', 'Cliffside Park', 'Clifton', 'Colonia',
        'Cranford', 'Denville', 'Dover', 'Dumont', 'East Brunswick', 'East Orange', 'Edison',
        'Elizabeth', 'Elmwood Park', 'Englewood', 'Ewing', 'Fair Lawn', 'Fords', 'Fort Lee',
        'Garfield', 'Glassboro', 'Hackensack', 'Harrison', 'Hawthorne', 'Hillsborough',
        'Hillside', 'Hoboken', 'Hopatcong Hills', 'Irvington', 'Iselin', 'Jackson',
        'Jersey City', 'Kearny', 'Lakewood', 'Linden', 'Lindenwold', 'Livingston', 'Lodi',
        'Long Branch', 'Lyndhurst', 'Madison', 'Mahwah', 'Maple Shade', 'Maplewood',
        'Marlboro', 'Mercerville-Hamilton Square', 'Middletown', 'Millburn', 'Millville',
        'Montclair', 'Morristown', 'Mount Laurel', 'New Brunswick', 'New Milford', 'Newark',
        'North Arlington', 'North Bergen', 'North Brunswick', 'North Plainfield', 'Nutley',
        'Ocean Acres', 'Old Bridge', 'Orange', 'Palisades Park', 'Paramus', 'Parsippany',
        'Passaic', 'Paterson', 'Pennsauken', 'Perth Amboy', 'Piscataway', 'Plainfield',
        'Pleasantville', 'Point Pleasant', 'Princeton', 'Rahway', 'Ramsey', 'Randolph',
        'Ridgewood', 'Roselle', 'Rutherford', 'Sayreville', 'Sayreville Junction',
        'Scotch Plains', 'Secaucus', 'Sewell', 'Sicklerville', 'Somerset', 'South Old Bridge',
        'South Orange', 'South Plainfield', 'South River', 'South Vineland', 'Sparta',
        'Summit', 'Teaneck', 'Tinton Falls', 'Toms River', 'Trenton', 'Union', 'Union City',
        'Vincentown', 'Vineland', 'Warren Township', 'Wayne', 'West Milford', 'West New York',
        'West Orange', 'Westfield', 'Williamstown', 'Willingboro', 'Woodbridge', 'Wyckoff',
    ],
    "NM": [
        'Alamogordo', 'Albuquerque', 'Carlsbad', 'Clovis', 'Enchanted Hills', 'Farmington',
        'Gallup', 'Hobbs', 'Las Cruces', 'Los Lunas', 'Rio Rancho', 'Roswell', 'Santa Fe',
        'South Valley', 'Sunland Park',
    ],
    "NV": [
        'Boulder City', 'Carson City', 'Elko', 'Enterprise', 'Fernley', 'Henderson',
        'Las Vegas', 'Mesquite', 'North Las Vegas', 'Pahrump', 'Paradise', 'Reno',
        'Spanish Springs', 'Sparks', 'Spring Valley', 'Summerlin South', 'Sun Valley',
        'Sunrise Manor', 'Whitney', 'Winchester',
    ],
    "NY": [
        'Albany', 'Amherst', 'Amsterdam', 'Astoria', 'Auburn', 'Baldwin', 'Batavia',
        'Bath Beach', 'Bay Shore', 'Baychester', 'Bayside', 'Bellmore', 'Bensonhurst',
        'Bethpage', 'Binghamton', 'Borough Park', 'Brentwood', 'Briarwood', 'Brighton',
        'Brighton Beach', 'Brooklyn', 'Brooklyn Heights', 'Brownsville', 'Buffalo', 'Bushwick',
        'Cambria Heights', 'Canarsie', 'Centereach', 'Central Islip', 'Cheektowaga',
        'Chinatown', 'Cicero', 'Clay', 'Clifton Park', 'Cohoes', 'College Point', 'Commack',
        'Coney Island', 'Copiague', 'Coram', 'Corona', 'Cortland', 'Cortlandt Manor',
        'Cypress Hills', 'Deer Park', 'Depew', 'Dix Hills', 'Dyker Heights', 'East Amherst',
        'East Elmhurst', 'East Flatbush', 'East Harlem', 'East Massapequa', 'East Meadow',
        'East New York', 'East Northport', 'East Patchogue', 'East Setauket', 'East Tremont',
        'East Village', 'Eastchester', 'Eggertsville', 'Elmhurst', 'Elmira', 'Elmont',
        'Emerson Hill', 'Far Rockaway', 'Farmingville', 'Financial District', 'Flatbush',
        'Flatlands', 'Floral Park', 'Fordham', 'Forest Hills', 'Fort Hamilton',
        'Franklin Square', 'Freeport', 'Fresh Meadows', 'Garden City', 'Gates-North Gates',
        'Glen Cove', 'Glendale', 'Glenville', 'Gloversville', 'Gramercy Park', 'Grand Island',
        'Graniteville', 'Gravesend', 'Great Kills', 'Greenburgh', 'Greenpoint', 'Harlem',
        'Harrison', 'Hauppauge', "Hell's Kitchen", 'Hempstead', 'Henrietta', 'Hicksville',
        'Hillside', 'Holbrook', 'Hollis', 'Holtsville', 'Howard Beach', 'Huntington',
        'Huntington Station', 'Hunts Point', 'Irondequoit', 'Islip', 'Ithaca',
        'Jackson Heights', 'Jamaica', 'Jamestown', 'Kenmore', 'Kensington', 'Kew Gardens',
        'Kew Gardens Hills', 'Kings Bridge', 'Kings Park', 'Kingston', 'Kiryas Joel',
        'Lackawanna', 'Lake Ronkonkoma', 'Latham', 'Laurelton', 'Levittown', 'Lindenhurst',
        'Lockport', 'Long Beach', 'Long Island City', 'Lynbrook', 'Mamaroneck', 'Manhattan',
        'Manhattan Valley', 'Mariners Harbor', 'Maspeth', 'Massapequa', 'Massapequa Park',
        'Mastic', 'Medford', 'Melrose', 'Melville', 'Merrick', 'Middle Village', 'Middletown',
        'Mineola', 'Monsey', 'Morningside Heights', 'Morris Heights', 'Morrisania',
        'Mott Haven', 'Mount Vernon', 'Nanuet', 'New City', 'New Rochelle', 'New Springville',
        'New York City', 'Newburgh', 'Niagara Falls', 'North Amityville', 'North Babylon',
        'North Bay Shore', 'North Bellmore', 'North Massapequa', 'North Tonawanda',
        'North Valley Stream', 'Oceanside', 'Ossining', 'Oswego', 'Ozone Park', 'Park Slope',
        'Parkchester', 'Pearl River', 'Peekskill', 'Plainview', 'Plattsburgh', 'Port Chester',
        'Port Richmond', 'Port Washington', 'Poughkeepsie', 'Queens', 'Queens Village',
        'Queensbury', 'Rego Park', 'Richmond Hill', 'Ridgewood', 'Rochester',
        'Rockville Centre', 'Rome', 'Ronkonkoma', 'Roosevelt', 'Rosedale', 'Rossville',
        'Rotterdam', 'Rye', 'Saratoga Springs', 'Sayville', 'Scarsdale', 'Schenectady',
        'Seaford', 'Selden', 'Setauket-East Setauket', 'Sheepshead Bay', 'Shirley',
        'Smithtown', 'South Ozone Park', 'Spring Valley', 'Springfield Gardens',
        'Staten Island', 'Sunnyside', 'Sunset Park', 'Syosset', 'Syracuse', 'Terrace Heights',
        'The Bronx', 'Throgs Neck', 'Times Square', 'Tremont', 'Troy', 'Uniondale',
        'Unionport', 'University Heights', 'Upper West Side', 'Utica', 'Valley Stream',
        'Van Nest', 'Vestal', 'Wakefield', 'Wantagh', 'Washington Heights', 'Watertown',
        'West Albany', 'West Babylon', 'West Hempstead', 'West Islip', 'West Seneca',
        'West Village', 'Westbury', 'White Plains', 'Whitestone', 'Williamsburg', 'Wilton',
        'Woodhaven', 'Woodmere', 'Woodrow', 'Woodside', 'Yonkers',
    ],
    "OH": [
        'Akron', 'Alliance', 'Ashland', 'Ashtabula', 'Athens', 'Aurora', 'Austintown', 'Avon',
        'Avon Center', 'Avon Lake', 'Barberton', 'Bay Village', 'Beavercreek', 'Berea',
        'Boardman', 'Bowling Green', 'Broadview Heights', 'Brook Park', 'Brunswick', 'Canton',
        'Centerville', 'Chillicothe', 'Cincinnati', 'Clark-Fulton', 'Cleveland',
        'Cleveland Heights', 'Collinwood', 'Columbus', 'Cuyahoga Falls', 'Dayton', 'Defiance',
        'Delaware', 'Detroit-Shoreway', 'Dublin', 'East Cleveland', 'Eastlake', 'Elyria',
        'Euclid', 'Fairborn', 'Fairfield', 'Fairview Park', 'Findlay', 'Forest Park',
        'Fremont', 'Gahanna', 'Garfield Heights', 'Glenville', 'Green', 'Grove City',
        'Hamilton', 'Hilliard', 'Hough', 'Huber Heights', 'Hudson', 'Kent', 'Kettering',
        'Lakewood', 'Lancaster', 'Lebanon', 'Lima', 'Lorain', 'Mansfield', 'Maple Heights',
        'Marion', 'Marysville', 'Mason', 'Massillon', 'Mayfield Heights', 'Medina', 'Mentor',
        'Miamisburg', 'Middleburg Heights', 'Middletown', 'Mount Vernon', 'New Philadelphia',
        'Newark', 'Niles', 'North Canton', 'North Olmsted', 'North Ridgeville',
        'North Royalton', 'Norwalk', 'Norwood', 'Oregon', 'Oxford', 'Painesville', 'Parma',
        'Parma Heights', 'Pataskala', 'Perrysburg', 'Pickerington', 'Piqua', 'Portsmouth',
        'Reynoldsburg', 'Riverside', 'Rocky River', 'Sandusky', 'Shaker Heights', 'Sidney',
        'Solon', 'South Euclid', 'Springboro', 'Springfield', 'Steubenville', 'Stow',
        'Streetsboro', 'Strongsville', 'Sylvania', 'Tallmadge', 'Tiffin', 'Toledo', 'Trotwood',
        'Troy', 'Twinsburg', 'Upper Arlington', 'Vandalia', 'Wadsworth', 'Warren',
        'Westerville', 'Westlake', 'White Oak', 'Whitehall', 'Willoughby', 'Wooster', 'Xenia',
        'Youngstown', 'Zanesville',
    ],
    "OK": [
        'Ada', 'Altus', 'Ardmore', 'Bartlesville', 'Bethany', 'Bixby', 'Broken Arrow',
        'Chickasha', 'Claremore', 'Del City', 'Duncan', 'Durant', 'Edmond', 'El Reno', 'Enid',
        'Jenks', 'Lawton', 'McAlester', 'Midwest City', 'Moore', 'Muskogee', 'Mustang',
        'Norman', 'Oklahoma City', 'Owasso', 'Ponca City', 'Sand Springs', 'Sapulpa',
        'Shawnee', 'Stillwater', 'Tahlequah', 'Tulsa', 'Yukon',
    ],
    "OR": [
        'Albany', 'Aloha', 'Altamont', 'Ashland', 'Beaverton', 'Bend', 'Bethany', 'Canby',
        'Central Point', 'Coos Bay', 'Corvallis', 'Dallas', 'Eugene', 'Forest Grove',
        'Four Corners', 'Grants Pass', 'Gresham', 'Happy Valley', 'Hayesville', 'Hermiston',
        'Hillsboro', 'Keizer', 'Klamath Falls', 'Lake Oswego', 'Lebanon', 'Lents',
        'McMinnville', 'Medford', 'Milwaukie', 'Newberg', 'Oak Grove', 'Oregon City',
        'Pendleton', 'Portland', 'Redmond', 'Roseburg', 'Salem', 'Sherwood', 'Springfield',
        'The Dalles', 'Tigard', 'Troutdale', 'Tualatin', 'West Linn', 'Wilsonville',
        'Woodburn',
    ],
    "PA": [
        'Abington', 'Allentown', 'Allison Park', 'Altoona', 'Back Mountain', 'Baldwin',
        'Bensalem', 'Bethel Park', 'Bethlehem', 'Bustleton', 'Carlisle', 'Center City',
        'Chambersburg', 'Chester', 'Cobbs Creek', 'Cranberry Township', 'Drexel Hill',
        'East Mount Airy', 'Easton', 'Elmwood', 'Erie', 'Fishtown', 'Fox Chase', 'Frankford',
        'Haddington', 'Hanover', 'Harrisburg', 'Hartranft', 'Havertown', 'Hazleton',
        'Hermitage', 'Holmesburg', 'Hunting Park', 'Johnstown', 'Juniata Park',
        'King of Prussia', 'Kingsessing', 'Lancaster', 'Lansdale', 'Lawndale', 'Lebanon',
        'Levittown', 'Limerick', 'Logan', 'Lower Moyamensing', 'McKeesport', 'Monroeville',
        'Mount Lebanon', 'Murrysville', 'New Castle', 'Nicetown-Tioga', 'Norristown', 'Olney',
        'Overbrook', 'Oxford Circle', 'Parkwood Manor', 'Penn Hills', 'Pennsport',
        'Philadelphia', 'Phoenixville', 'Pittsburgh', 'Plum', 'Point Breeze', 'Port Richmond',
        'Pottstown', 'Radnor', 'Reading', 'Rhawnhurst', 'Rittenhouse', 'Scranton', 'Somerton',
        'Springfield', 'State College', 'Strawberry Mansion', 'Tacony', 'University City',
        'Upper Saint Clair', 'Wayne', 'West Chester', 'West Mifflin', 'West Oak Lane',
        'Wharton', 'Whitehall Township', 'Whitman', 'Wilkes-Barre', 'Wilkinsburg',
        'Williamsport', 'Willow Grove', 'Wissinoming', 'York',
    ],
    "RI": [
        'Barrington', 'Bristol', 'Central Falls', 'Coventry', 'Cranston', 'Cumberland',
        'East Providence', 'Johnston', 'Lincoln', 'Middletown', 'Narragansett', 'Newport',
        'North Kingstown', 'North Providence', 'Pawtucket', 'Portsmouth', 'Providence',
        'Smithfield', 'South Kingstown', 'Warwick', 'West Warwick', 'Westerly', 'Woonsocket',
    ],
    "SC": [
        'Aiken', 'Anderson', 'Bluffton', 'Charleston', 'Clemson', 'Columbia', 'Conway',
        'Easley', 'Florence', 'Goose Creek', 'Greenville', 'Greenwood', 'Greer', 'Hanahan',
        'Hilton Head', 'Hilton Head Island', 'Lexington', 'Mauldin', 'Mount Pleasant',
        'Myrtle Beach', 'North Augusta', 'North Charleston', 'North Myrtle Beach', 'Rock Hill',
        'Saint Andrews', 'Seven Oaks', 'Simpsonville', 'Socastee', 'Spartanburg',
        'Summerville', 'Sumter', 'Taylors', 'Wade Hampton', 'West Columbia',
    ],
    "SD": [
        'Aberdeen', 'Brookings', 'Mitchell', 'Rapid City', 'Sioux Falls', 'Watertown',
    ],
    "TN": [
        'Bartlett', 'Brentwood', 'Brentwood Estates', 'Bristol', 'Chattanooga', 'Clarksville',
        'Cleveland', 'Collierville', 'Columbia', 'Cookeville', 'Cordova', 'Dickson',
        'Dyersburg', 'East Brainerd', 'East Chattanooga', 'East Ridge', 'Ellendale',
        'Farragut', 'Franklin', 'Gallatin', 'Germantown', 'Goodlettsville', 'Greeneville',
        'Hendersonville', 'Hermitage', 'Jackson', 'Johnson City', 'Kingsport', 'Knoxville',
        'La Vergne', 'Lebanon', 'Maryville', 'Memphis', 'Morristown', 'Mount Juliet',
        'Murfreesboro', 'Nashville', 'New South Memphis', 'Oak Ridge', 'Sevierville',
        'Shelbyville', 'Smyrna', 'Spring Hill', 'Springfield', 'Tullahoma',
    ],
    "TX": [
        'Abilene', 'Addison', 'Alamo', 'Aldine', 'Alice', 'Alief', 'Allen', 'Alton', 'Alvin',
        'Amarillo', 'Angleton', 'Arlington', 'Atascocita', 'Austin', 'Balch Springs',
        'Bay City', 'Baytown', 'Beaumont', 'Bedford', 'Bellaire', 'Belton', 'Benbrook',
        'Big Spring', 'Brenham', 'Brownsville', 'Brownwood', 'Brushy Creek', 'Bryan',
        'Burleson', 'Canyon Lake', 'Carrollton', 'Cedar Hill', 'Cedar Park', 'Celina',
        'Channelview', 'Cibolo', 'Cinco Ranch', 'Cleburne', 'Cloverleaf', 'College Station',
        'Colleyville', 'Conroe', 'Converse', 'Coppell', 'Copperas Cove', 'Corinth',
        'Corpus Christi', 'Corsicana', 'Cypress', 'Dallas', 'DeSoto', 'Deer Park', 'Del Rio',
        'Denison', 'Denton', 'Dickinson', 'Donna', 'Dumas', 'Duncanville', 'Eagle Pass',
        'Edinburg', 'El Paso', 'Ennis', 'Euless', 'Farmers Branch', 'Flower Mound', 'Forney',
        'Fort Cavazos', 'Fort Worth', 'Fresno', 'Friendswood', 'Frisco', 'Gainesville',
        'Galveston', 'Garland', 'Gatesville', 'Georgetown', 'Grand Prairie', 'Grapevine',
        'Greenville', 'Groves', 'Haltom City', 'Harker Heights', 'Harlingen', 'Hereford',
        'Highland Village', 'Horizon City', 'Houston', 'Humble', 'Huntsville', 'Hurst',
        'Hutto', 'Irving', 'Jollyville', 'Katy', 'Keller', 'Kerrville', 'Killeen',
        'Kingsville', 'Kyle', 'La Marque', 'La Porte', 'Lake Jackson', 'Lancaster', 'Laredo',
        'League City', 'Leander', 'Lewisville', 'Little Elm', 'Live Oak', 'Longview',
        'Lubbock', 'Lufkin', 'Mansfield', 'Marshall', 'McAllen', 'McKinney', 'Mercedes',
        'Mesquite', 'Midland', 'Midlothian', 'Mission', 'Mission Bend', 'Missouri City',
        'Mount Pleasant', 'Murphy', 'Nacogdoches', 'Nederland', 'New Braunfels', 'New Caney',
        'New Territory', 'North Richland Hills', 'Odessa', 'Orange', 'Palestine', 'Pampa',
        'Paris', 'Pasadena', 'Pearland', 'Pecan Grove', 'Pflugerville', 'Pharr', 'Plainview',
        'Plano', 'Port Arthur', 'Portland', 'Prosper', 'Richardson', 'Rockwall', 'Rosenberg',
        'Round Rock', 'Rowlett', 'Sachse', 'Saginaw', 'San Angelo', 'San Antonio',
        'San Benito', 'San Juan', 'San Marcos', 'Schertz', 'Seagoville', 'Seguin', 'Sherman',
        'Socorro', 'Socorro Mission Number 1 Colonia', 'South Houston', 'Southlake', 'Spring',
        'Stafford', 'Stephenville', 'Sugar Land', 'Sulphur Springs', 'Taylor', 'Temple',
        'Terrell', 'Texarkana', 'Texas City', 'The Colony', 'The Trails of Frisco',
        'The Woodlands', 'Tyler', 'Universal City', 'University Park', 'University of Texas',
        'Uvalde', 'Victoria', 'Waco', 'Watauga', 'Waxahachie', 'Weatherford', 'Weslaco',
        'West Odessa', 'West University Place', 'White Settlement', 'Wichita Falls', 'Wylie',
    ],
    "UT": [
        'American Fork', 'Bountiful', 'Brigham City', 'Cedar City', 'Centerville',
        'Clearfield', 'Clinton', 'Cottonwood Heights', 'Draper', 'Eagle Mountain',
        'East Millcreek', 'Farmington', 'Herriman', 'Highland', 'Holladay', 'Hurricane',
        'Kaysville', 'Kearns', 'Layton', 'Lehi', 'Logan', 'Magna', 'Midvale', 'Millcreek',
        'Murray', 'North Ogden', 'North Salt Lake', 'Ogden', 'Orem', 'Payson',
        'Pleasant Grove', 'Provo', 'Riverton', 'Roy', 'Saint George', 'Salt Lake City',
        'Sandy', 'Sandy Hills', 'Saratoga Springs', 'South Jordan', 'South Jordan Heights',
        'South Ogden', 'South Salt Lake', 'Spanish Fork', 'Springville', 'Syracuse',
        'Taylorsville', 'Tooele', 'Washington', 'West Jordan', 'West Valley City',
    ],
    "VA": [
        'Alexandria', 'Annandale', 'Arlington', 'Ashburn', 'Baileys Crossroads', 'Blacksburg',
        'Bon Air', 'Bristol', 'Buckhall', 'Burke', 'Cave Spring', 'Centreville', 'Chantilly',
        'Charlottesville', 'Cherry Hill', 'Chesapeake', 'Chester', 'Christiansburg',
        'Colonial Heights', 'Culpeper', 'Dale City', 'Danville', 'East Hampton', 'Fairfax',
        'Fort Hunt', 'Franconia', 'Fredericksburg', 'Front Royal', 'Great Falls', 'Hampton',
        'Harrisonburg', 'Herndon', 'Highland Springs', 'Hopewell', 'Hybla Valley', 'Idylwood',
        'Lake Ridge', 'Laurel', 'Leesburg', 'Lincolnia', 'Linton Hall', 'Lorton', 'Lynchburg',
        'Manassas', 'Manassas Park', 'McLean', 'Meadowbrook', 'Mechanicsville', 'Merrifield',
        'Midlothian', 'Montclair', 'Newport News', 'Norfolk', 'Oak Hill', 'Oakton',
        'Petersburg', 'Portsmouth', 'Portsmouth Heights', 'Radford', 'Reston', 'Richmond',
        'Roanoke', 'Rose Hill', 'Salem', 'Short Pump', 'South Riding', 'South Suffolk',
        'Springfield', 'Staunton', 'Sterling', 'Sudley', 'Suffolk', 'Tuckahoe', 'Tysons',
        'Vienna', 'Virginia Beach', 'Waynesboro', 'West Falls Church', 'West Lynchburg',
        'West Springfield', 'Williamsburg', 'Winchester', 'Wolf Trap', 'Woodlawn',
    ],
    "VT": [
        'Burlington', 'Colchester', 'Rutland', 'South Burlington',
    ],
    "WA": [
        'Aberdeen', 'Anacortes', 'Arlington', 'Auburn', 'Bainbridge Island', 'Battle Ground',
        'Bellevue', 'Bellingham', 'Bonney Lake', 'Bothell', 'Bothell West', 'Bremerton',
        'Bryn Mawr-Skyway', 'Burien', 'Camas', 'Centralia', 'City of Sammamish',
        'Columbia City', 'Cottage Lake', 'Covington', 'Des Moines', 'East Hill-Meridian',
        'Eastmont', 'Edmonds', 'Ellensburg', 'Everett', 'Fairwood', 'Federal Way',
        'Five Corners', 'Frederickson', 'Graham', 'Hazel Dell', 'Inglewood-Finn Hill',
        'Issaquah', 'Kenmore', 'Kennewick', 'Kent', 'Kirkland', 'Lacey', 'Lake Stevens',
        'Lakewood', 'Longview', 'Lynnwood', 'Maple Valley', 'Martha Lake', 'Marysville',
        'Mercer Island', 'Mill Creek', 'Mill Creek East', 'Monroe', 'Moses Lake',
        'Mount Vernon', 'Mountlake Terrace', 'Mukilteo', 'North Creek', 'Oak Harbor',
        'Olympia', 'Opportunity', 'Orchards', 'Parkland', 'Pasco',
        'Picnic Point-North Lynnwood', 'Port Angeles', 'Pullman', 'Puyallup', 'Redmond',
        'Renton', 'Richland', 'Salmon Creek', 'Sammamish', 'SeaTac', 'Seattle', 'Shoreline',
        'Silver Firs', 'Silverdale', 'South Hill', 'Spanaway', 'Spokane', 'Spokane Valley',
        'Sunnyside', 'Tacoma', 'Tri-Cities', 'Tukwila', 'Tumwater', 'Union Hill-Novelty Hill',
        'University Place', 'Vancouver', 'Walla Walla', 'Washougal', 'Wenatchee',
        'West Lake Sammamish', 'West Lake Stevens', 'Yakima',
    ],
    "WI": [
        'Appleton', 'Ashwaubenon', 'Beaver Dam', 'Bellevue', 'Beloit', 'Brookfield',
        'Caledonia', 'Cudahy', 'De Pere', 'Eau Claire', 'Fitchburg', 'Fond du Lac', 'Franklin',
        'Germantown', 'Green Bay', 'Greenfield', 'Howard', 'Janesville', 'Kaukauna', 'Kenosha',
        'La Crosse', 'Madison', 'Manitowoc', 'Marshfield', 'Menasha', 'Menomonee Falls',
        'Menomonie', 'Mequon', 'Middleton', 'Milwaukee', 'Mount Pleasant', 'Muskego', 'Neenah',
        'New Berlin', 'North La Crosse', 'Oak Creek', 'Oconomowoc', 'Onalaska', 'Oshkosh',
        'Pleasant Prairie', 'Racine', 'River Falls', 'Sheboygan', 'South Milwaukee',
        'Stevens Point', 'Sun Prairie', 'Superior', 'Watertown', 'Waukesha', 'Wausau',
        'Wauwatosa', 'West Allis', 'West Bend', 'Weston', 'Wisconsin Rapids',
    ],
    "WV": [
        'Beckley', 'Charleston', 'Clarksburg', 'Fairmont', 'Huntington', 'Martinsburg',
        'Morgantown', 'Parkersburg', 'Weirton', 'Weirton Heights', 'Wheeling',
    ],
    "WY": [
        'Casper', 'Cheyenne', 'Gillette', 'Laramie', 'Rock Springs', 'Sheridan',
    ],
}
CANADA_PROVINCES = [
    ("AB", "Alberta"), ("BC", "British Columbia"), ("MB", "Manitoba"),
    ("NB", "New Brunswick"), ("NL", "Newfoundland and Labrador"),
    ("NS", "Nova Scotia"), ("NT", "Northwest Territories"), ("NU", "Nunavut"),
    ("ON", "Ontario"), ("PE", "Prince Edward Island"), ("QC", "Quebec"),
    ("SK", "Saskatchewan"), ("YT", "Yukon"),
]

# GLOBAL — continent/region tier, sits above countries.
REGIONS = [
    ("ASIA", "Asia"), ("EUROPE", "Europe"), ("AFRICA", "Africa"),
    ("NORTH_AMERICA", "North America"), ("SOUTH_AMERICA", "South America"),
    ("OCEANIA", "Oceania"),
]

# Every one of the 241 seeded countries mapped to one of the REGIONS codes
# above. A handful of transcontinental countries (Russia, Türkiye,
# Kazakhstan, Georgia, Cyprus, etc.) are placed by common convention rather
# than strict landmass split.
COUNTRY_REGIONS = {
    "AF": "ASIA", "AX": "EUROPE", "AL": "EUROPE", "DZ": "AFRICA",
    "AS": "OCEANIA", "AD": "EUROPE", "AO": "AFRICA", "AI": "NORTH_AMERICA",
    "AG": "NORTH_AMERICA", "AR": "SOUTH_AMERICA", "AM": "ASIA", "AW": "NORTH_AMERICA",
    "AU": "OCEANIA", "AT": "EUROPE", "AZ": "ASIA", "BS": "NORTH_AMERICA",
    "BH": "ASIA", "BD": "ASIA", "BB": "NORTH_AMERICA", "BY": "EUROPE",
    "BE": "EUROPE", "BZ": "NORTH_AMERICA", "BJ": "AFRICA", "BM": "NORTH_AMERICA",
    "BT": "ASIA", "BO": "SOUTH_AMERICA", "BQ": "NORTH_AMERICA", "BA": "EUROPE",
    "BW": "AFRICA", "BR": "SOUTH_AMERICA", "BN": "ASIA", "BG": "EUROPE",
    "BF": "AFRICA", "BI": "AFRICA", "CV": "AFRICA", "KH": "ASIA",
    "CM": "AFRICA", "CA": "NORTH_AMERICA", "KY": "NORTH_AMERICA", "CF": "AFRICA",
    "TD": "AFRICA", "CL": "SOUTH_AMERICA", "CN": "ASIA", "CX": "OCEANIA",
    "CC": "OCEANIA", "CO": "SOUTH_AMERICA", "KM": "AFRICA", "CD": "AFRICA",
    "CG": "AFRICA", "CK": "OCEANIA", "CR": "NORTH_AMERICA", "CI": "AFRICA",
    "HR": "EUROPE", "CU": "NORTH_AMERICA", "CW": "NORTH_AMERICA", "CY": "ASIA",
    "CZ": "EUROPE", "DK": "EUROPE", "DJ": "AFRICA", "DM": "NORTH_AMERICA",
    "DO": "NORTH_AMERICA", "EC": "SOUTH_AMERICA", "EG": "AFRICA", "SV": "NORTH_AMERICA",
    "GQ": "AFRICA", "ER": "AFRICA", "EE": "EUROPE", "SZ": "AFRICA",
    "ET": "AFRICA", "FK": "SOUTH_AMERICA", "FO": "EUROPE", "FJ": "OCEANIA",
    "FI": "EUROPE", "FR": "EUROPE", "GF": "SOUTH_AMERICA", "PF": "OCEANIA",
    "GA": "AFRICA", "GM": "AFRICA", "GE": "ASIA", "DE": "EUROPE",
    "GH": "AFRICA", "GI": "EUROPE", "GR": "EUROPE", "GL": "NORTH_AMERICA",
    "GD": "NORTH_AMERICA", "GP": "NORTH_AMERICA", "GU": "OCEANIA", "GT": "NORTH_AMERICA",
    "GG": "EUROPE", "GN": "AFRICA", "GW": "AFRICA", "GY": "SOUTH_AMERICA",
    "HT": "NORTH_AMERICA", "VA": "EUROPE", "HN": "NORTH_AMERICA", "HK": "ASIA",
    "HU": "EUROPE", "IS": "EUROPE", "IN": "ASIA", "ID": "ASIA",
    "IR": "ASIA", "IQ": "ASIA", "IE": "EUROPE", "IM": "EUROPE",
    "IL": "ASIA", "IT": "EUROPE", "JM": "NORTH_AMERICA", "JP": "ASIA",
    "JE": "EUROPE", "JO": "ASIA", "KZ": "ASIA", "KE": "AFRICA",
    "KI": "OCEANIA", "KP": "ASIA", "KR": "ASIA", "KW": "ASIA",
    "KG": "ASIA", "LA": "ASIA", "LV": "EUROPE", "LB": "ASIA",
    "LS": "AFRICA", "LR": "AFRICA", "LY": "AFRICA", "LI": "EUROPE",
    "LT": "EUROPE", "LU": "EUROPE", "MO": "ASIA", "MK": "EUROPE",
    "MG": "AFRICA", "MW": "AFRICA", "MY": "ASIA", "MV": "ASIA",
    "ML": "AFRICA", "MT": "EUROPE", "MH": "OCEANIA", "MQ": "NORTH_AMERICA",
    "MR": "AFRICA", "MU": "AFRICA", "YT": "AFRICA", "MX": "NORTH_AMERICA",
    "FM": "OCEANIA", "MD": "EUROPE", "MC": "EUROPE", "MN": "ASIA",
    "ME": "EUROPE", "MS": "NORTH_AMERICA", "MA": "AFRICA", "MZ": "AFRICA",
    "MM": "ASIA", "NA": "AFRICA", "NR": "OCEANIA", "NP": "ASIA",
    "NL": "EUROPE", "NC": "OCEANIA", "NZ": "OCEANIA", "NI": "NORTH_AMERICA",
    "NE": "AFRICA", "NG": "AFRICA", "NU": "OCEANIA", "NF": "OCEANIA",
    "MP": "OCEANIA", "NO": "EUROPE", "OM": "ASIA", "PK": "ASIA",
    "PW": "OCEANIA", "PS": "ASIA", "PA": "NORTH_AMERICA", "PG": "OCEANIA",
    "PY": "SOUTH_AMERICA", "PE": "SOUTH_AMERICA", "PH": "ASIA", "PN": "OCEANIA",
    "PL": "EUROPE", "PT": "EUROPE", "PR": "NORTH_AMERICA", "QA": "ASIA",
    "RE": "AFRICA", "RO": "EUROPE", "RU": "EUROPE", "RW": "AFRICA",
    "BL": "NORTH_AMERICA", "SH": "AFRICA", "KN": "NORTH_AMERICA", "LC": "NORTH_AMERICA",
    "MF": "NORTH_AMERICA", "PM": "NORTH_AMERICA", "VC": "NORTH_AMERICA", "WS": "OCEANIA",
    "SM": "EUROPE", "ST": "AFRICA", "SA": "ASIA", "SN": "AFRICA",
    "RS": "EUROPE", "SC": "AFRICA", "SL": "AFRICA", "SG": "ASIA",
    "SX": "NORTH_AMERICA", "SK": "EUROPE", "SI": "EUROPE", "SB": "OCEANIA",
    "SO": "AFRICA", "ZA": "AFRICA", "SS": "AFRICA", "ES": "EUROPE",
    "LK": "ASIA", "SD": "AFRICA", "SR": "SOUTH_AMERICA", "SE": "EUROPE",
    "CH": "EUROPE", "SY": "ASIA", "TW": "ASIA", "TJ": "ASIA",
    "TZ": "AFRICA", "TH": "ASIA", "TL": "ASIA", "TG": "AFRICA",
    "TK": "OCEANIA", "TO": "OCEANIA", "TT": "NORTH_AMERICA", "TN": "AFRICA",
    "TR": "ASIA", "TM": "ASIA", "TC": "NORTH_AMERICA", "TV": "OCEANIA",
    "UG": "AFRICA", "UA": "EUROPE", "AE": "ASIA", "GB": "EUROPE",
    "US": "NORTH_AMERICA", "UY": "SOUTH_AMERICA", "UZ": "ASIA", "VU": "OCEANIA",
    "VE": "SOUTH_AMERICA", "VN": "ASIA", "VG": "NORTH_AMERICA", "VI": "NORTH_AMERICA",
    "WF": "OCEANIA", "EH": "AFRICA", "YE": "ASIA", "ZM": "AFRICA",
    "ZW": "AFRICA",
}

# Country calling codes (source: Wikipedia "List of country calling
# codes", ITU-T E.164 numbering plan). NANP members are stored as
# "+1-NNN" (area code) since bare "+1" doesn't distinguish them; a few
# dependent territories share their parent's numbering plan.
COUNTRY_CALLING_CODES = {
    "US": "+1", "CA": "+1", "BS": "+1-242", "BB": "+1-246", "AI": "+1-264",
    "AG": "+1-268", "VG": "+1-284", "KY": "+1-345", "BM": "+1-441",
    "GD": "+1-473", "TC": "+1-649", "JM": "+1-876", "MP": "+1-670",
    "GU": "+1-671", "AS": "+1-684", "SX": "+1-721", "LC": "+1-758",
    "DM": "+1-767", "VC": "+1-784", "DO": "+1-809", "TT": "+1-868",
    "KN": "+1-869", "VI": "+1-340", "MS": "+1-664", "PR": "+1-787",
    "EG": "+20", "SS": "+211", "MA": "+212", "EH": "+212", "DZ": "+213",
    "TN": "+216", "LY": "+218", "GM": "+220", "SN": "+221", "MR": "+222",
    "ML": "+223", "GN": "+224", "CI": "+225", "BF": "+226", "NE": "+227",
    "TG": "+228", "BJ": "+229", "MU": "+230", "LR": "+231", "SL": "+232",
    "GH": "+233", "NG": "+234", "TD": "+235", "CF": "+236", "CM": "+237",
    "CV": "+238", "ST": "+239", "GQ": "+240", "GA": "+241", "CG": "+242", "CD": "+243",
    "AO": "+244", "GW": "+245", "SC": "+248", "SD": "+249", "RW": "+250",
    "ET": "+251", "SO": "+252", "DJ": "+253", "KE": "+254", "TZ": "+255",
    "UG": "+256", "BI": "+257", "MZ": "+258", "ZM": "+260", "MG": "+261",
    "RE": "+262", "YT": "+262", "ZW": "+263", "NA": "+264", "MW": "+265",
    "LS": "+266", "BW": "+267", "SZ": "+268", "KM": "+269", "ZA": "+27",
    "SH": "+290", "ER": "+291", "AW": "+297", "FO": "+298", "GL": "+299",
    "GR": "+30", "NL": "+31", "BE": "+32", "FR": "+33", "ES": "+34",
    "GI": "+350", "PT": "+351", "LU": "+352", "IE": "+353", "IS": "+354",
    "AL": "+355", "MT": "+356", "CY": "+357", "FI": "+358", "AX": "+358",
    "BG": "+359", "HU": "+36", "LT": "+370", "LV": "+371", "EE": "+372",
    "MD": "+373", "AM": "+374", "BY": "+375", "AD": "+376", "MC": "+377",
    "SM": "+378", "VA": "+379", "UA": "+380", "RS": "+381", "ME": "+382",
    "HR": "+385", "SI": "+386", "BA": "+387", "MK": "+389", "IT": "+39",
    "RO": "+40", "CH": "+41", "CZ": "+420", "SK": "+421", "LI": "+423",
    "AT": "+43", "GB": "+44", "GG": "+44", "JE": "+44", "IM": "+44",
    "DK": "+45", "SE": "+46", "NO": "+47", "PL": "+48", "DE": "+49",
    "FK": "+500", "BZ": "+501", "GT": "+502", "SV": "+503", "HN": "+504",
    "NI": "+505", "CR": "+506", "PA": "+507", "PM": "+508", "HT": "+509",
    "PE": "+51", "MX": "+52", "CU": "+53", "AR": "+54", "BR": "+55",
    "CL": "+56", "CO": "+57", "VE": "+58", "GP": "+590", "BL": "+590",
    "MF": "+590", "BO": "+591", "GY": "+592", "EC": "+593", "GF": "+594",
    "PY": "+595", "MQ": "+596", "SR": "+597", "UY": "+598", "CW": "+599",
    "BQ": "+599", "MY": "+60", "AU": "+61", "CC": "+61", "CX": "+61",
    "ID": "+62", "PH": "+63", "NZ": "+64", "PN": "+64", "SG": "+65",
    "TH": "+66", "TL": "+670", "BN": "+673", "NR": "+674", "PG": "+675",
    "TO": "+676", "SB": "+677", "VU": "+678", "FJ": "+679", "PW": "+680",
    "WF": "+681", "CK": "+682", "NU": "+683", "WS": "+685", "KI": "+686",
    "NC": "+687", "TV": "+688", "PF": "+689", "TK": "+690", "FM": "+691",
    "MH": "+692", "NF": "+672", "RU": "+7", "KZ": "+7", "JP": "+81", "KR": "+82",
    "VN": "+84", "KP": "+850", "HK": "+852", "MO": "+853", "KH": "+855",
    "LA": "+856", "CN": "+86", "BD": "+880", "TW": "+886", "TR": "+90",
    "IN": "+91", "PK": "+92", "AF": "+93",
    "LK": "+94", "MM": "+95", "MV": "+960", "LB": "+961", "JO": "+962",
    "SY": "+963", "IQ": "+964", "KW": "+965", "SA": "+966", "YE": "+967",
    "OM": "+968", "PS": "+970", "AE": "+971", "IL": "+972", "BH": "+973",
    "QA": "+974", "BT": "+975", "MN": "+976", "NP": "+977", "IR": "+98",
    "TJ": "+992", "TM": "+993", "AZ": "+994", "GE": "+995", "KG": "+996",
    "UZ": "+998",
}


def _slug(label: str) -> str:
    return label.upper().replace("&", "AND").replace("/", "_").replace(" ", "_").replace("'", "").replace(".", "").replace("-", "_").replace(",", "")[:40]


def _seed_simple(db, table: str, tenant_id: int, labels):
    """Seed one TENANT-SCOPED lookup table for a specific tenant. Keyed on
    (tenant_id, code) — see schema.sql's per-tenant UNIQUE constraint on
    these tables — so re-running this for a tenant that already has its own
    (possibly since-edited) rows does not clobber anything."""
    for i, label in enumerate(labels):
        code = _slug(label)
        db.execute(
            f"INSERT OR IGNORE INTO {table} (tenant_id, code, label, sort_order, is_active) VALUES (?, ?, ?, ?, 1)",
            (tenant_id, code, label, i),
        )


def _seed_states(db, country_code, entries):
    """states is GLOBAL (no tenant_id) — real-world geography, shared by
    every tenant. Safe to call once ever; INSERT OR IGNORE makes repeat
    calls (e.g. from seeding a second tenant) no-ops.

    `entries` is a list of (code, label) tuples — code is None for
    countries whose provinces have no standard code. Label is always the
    full name, never just a code, so display is consistent across every
    country."""
    row = db.execute("SELECT country_id FROM countries WHERE code = ?", (country_code,)).fetchone()
    if not row:
        return
    for i, (code, label) in enumerate(entries):
        if code is None:
            exists = db.execute(
                "SELECT 1 FROM states WHERE country_id = ? AND code IS NULL AND label = ?",
                (row["country_id"], label),
            ).fetchone()
            if exists:
                continue
            db.execute(
                "INSERT INTO states (country_id, code, label, sort_order, is_active) VALUES (?, NULL, ?, ?, 1)",
                (row["country_id"], label, i),
            )
        else:
            db.execute(
                "INSERT OR IGNORE INTO states (country_id, code, label, sort_order, is_active) VALUES (?, ?, ?, ?, 1)",
                (row["country_id"], code, label, i),
            )


def _seed_cities(db, country_code, province_label, city_labels):
    """cities is GLOBAL (no tenant_id), FK to states. Safe to re-run —
    manual existence check per (state_id, label) since there's no unique
    code to key an OR IGNORE off. Called by seed_global_lookups() below,
    once per US state, to load US_CITIES; add another loop the same way to
    seed another country's cities later."""
    state = db.execute(
        "SELECT s.state_id FROM states s JOIN countries c ON c.country_id = s.country_id "
        "WHERE c.code = ? AND s.label = ?",
        (country_code, province_label),
    ).fetchone()
    if not state:
        return
    for i, label in enumerate(city_labels):
        exists = db.execute(
            "SELECT 1 FROM cities WHERE state_id = ? AND label = ?", (state["state_id"], label)
        ).fetchone()
        if exists:
            continue
        db.execute(
            "INSERT INTO cities (state_id, label, sort_order, is_active) VALUES (?, ?, ?, 1)",
            (state["state_id"], label, i),
        )


def _seed_nested(db, table: str, parent_fk: str, tenant_id: int, parent_id: int, parent_code: str, labels):
    """Seed a nested (child) lookup table — organization_subdomains here,
    same shape as knowledge_subdomains/content_subtypes in schema.sql. The
    child table's `code` column is UNIQUE(tenant_id, code) — NOT scoped by
    parent — so a child's code has to be unique across every parent's
    children, not just its own siblings. We get that by prefixing each
    child's own slug-code with its parent's slug-code (e.g. domain
    "AGRICULTURE_AND_FARMING" + subdomain "Dairy Farming" ->
    "AGRICULTURE_AND_FARMING_DAIRY_FARMING"). Safe to re-run: INSERT OR
    IGNORE keyed on (tenant_id, code)."""
    for i, label in enumerate(labels):
        code = f"{parent_code}_{_slug(label)}"
        db.execute(
            f"INSERT OR IGNORE INTO {table} (tenant_id, {parent_fk}, code, label, sort_order, is_active) "
            f"VALUES (?, ?, ?, ?, ?, 1)",
            (tenant_id, parent_id, code, label, i),
        )


def seed_organization_classification_lookups(db, tenant_id: int):
    """Seeds organization_size_categories, organization_domains, and
    organization_subdomains (one level nested under domains) for one
    tenant — the lookups behind the Organization form's Number of
    Employees / Size Category / Domain / SubDomain fields.

    Shared by two callers: seed_lookup_tables() below (a brand-new tenant,
    e.g. via `flask seed-tenant`) and db.py's schema-migration path (an
    existing, already-running tenant whose database is being upgraded in
    place). Both need the same real choices rather than empty dropdowns,
    so both call this one implementation. Safe to re-run: every insert is
    INSERT OR IGNORE keyed on (tenant_id, code), so re-running it for a
    tenant that already has its own (possibly since-edited) rows is a
    no-op for anything already there."""
    for i, (label, description, min_employees, max_employees) in enumerate(ORGANIZATION_SIZE_CATEGORIES):
        code = _slug(label)
        db.execute(
            "INSERT OR IGNORE INTO organization_size_categories "
            "(tenant_id, code, label, description, min_employees, max_employees, sort_order, is_active) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 1)",
            (tenant_id, code, label, description, min_employees, max_employees, i),
        )

    _seed_simple(db, "organization_domains", tenant_id, ORGANIZATION_DOMAINS)

    for domain_label in ORGANIZATION_DOMAINS:
        domain_code = _slug(domain_label)
        row = db.execute(
            "SELECT organization_domain_id FROM organization_domains WHERE tenant_id = ? AND code = ?",
            (tenant_id, domain_code),
        ).fetchone()
        if not row:
            continue
        _seed_nested(
            db, "organization_subdomains", "organization_domain_id", tenant_id,
            row["organization_domain_id"], domain_code,
            ORGANIZATION_SUBDOMAINS.get(domain_label, []),
        )

    db.commit()


def seed_global_lookups(db):
    """Seeds regions, countries, states, cities, and country_phone_codes —
    the GLOBAL (non-tenant-scoped) lookup tables, shared by every tenant.
    Safe to re-run for every new tenant; INSERT OR IGNORE (or an
    equivalent manual existence check) makes it a no-op once already
    populated."""
    for i, (code, label) in enumerate(REGIONS):
        db.execute(
            "INSERT OR IGNORE INTO regions (code, label, sort_order, is_active) VALUES (?, ?, ?, 1)",
            (code, label, i),
        )

    for i, (code, label) in enumerate(COUNTRIES):
        db.execute(
            "INSERT OR IGNORE INTO countries (code, label, sort_order, is_active) VALUES (?, ?, ?, 1)",
            (code, label, i),
        )

    # Assign each country's region_id (idempotent — always safe to re-set).
    for code, region_code in COUNTRY_REGIONS.items():
        db.execute(
            "UPDATE countries SET region_id = (SELECT region_id FROM regions WHERE code = ?) "
            "WHERE code = ?",
            (region_code, code),
        )

    _seed_states(db, "US", US_STATES)
    _seed_states(db, "CA", CANADA_PROVINCES)

    # US cities (see US_CITIES above) — keyed by state postal code, so map
    # each back to the full state label _seed_cities expects.
    us_state_labels = dict(US_STATES)
    for state_code, city_labels in US_CITIES.items():
        _seed_cities(db, "US", us_state_labels[state_code], city_labels)

    for code, calling_code in COUNTRY_CALLING_CODES.items():
        row = db.execute("SELECT country_id FROM countries WHERE code = ?", (code,)).fetchone()
        if row:
            db.execute(
                "INSERT OR IGNORE INTO country_phone_codes (country_id, calling_code, label, is_active) "
                "SELECT ?, ?, ?, 1 WHERE NOT EXISTS ("
                "  SELECT 1 FROM country_phone_codes WHERE country_id = ? AND calling_code = ?"
                ")",
                (row["country_id"], calling_code, f"{code} {calling_code}", row["country_id"], calling_code),
            )

    db.commit()


def seed_lookup_tables(db, tenant_id: int):
    """Seeds every TENANT-SCOPED lookup table GSS has, for one tenant —
    plus the global geography tables, which only actually insert once no
    matter how many tenants call this."""
    _seed_simple(db, "contact_categories", tenant_id, CONTACT_CATEGORIES)
    _seed_simple(db, "contact_titles", tenant_id, CONTACT_TITLES)
    _seed_simple(db, "contact_suffixes", tenant_id, CONTACT_SUFFIXES)
    _seed_simple(db, "professions", tenant_id, PROFESSIONS)
    _seed_simple(db, "contact_contexts", tenant_id, CONTACT_CONTEXTS)
    _seed_simple(db, "organization_types", tenant_id, ORGANIZATION_TYPES)
    _seed_simple(db, "organization_address_types", tenant_id, ORGANIZATION_ADDRESS_TYPES)
    _seed_simple(db, "organization_phone_types", tenant_id, ORGANIZATION_PHONE_TYPES)
    _seed_simple(db, "knowledge_domains", tenant_id, KNOWLEDGE_DOMAINS)
    _seed_simple(db, "content_types", tenant_id, CONTENT_TYPES)
    _seed_simple(db, "content_link_types", tenant_id, CONTENT_LINK_TYPES)
    seed_organization_classification_lookups(db, tenant_id)

    seed_global_lookups(db)
    db.commit()


def seed_business_card_sample_contact(db, tenant_id: int):
    """One-time sample contact ("Gallant Plumbing Services") with both a
    front and back Business Card image attached, so the Business Card
    field (see schema.sql's contacts.business_card_front_path/
    business_card_back_path and blueprints/contacts.py) is demonstrated on
    a real record right away instead of shipping as an empty, undiscovered
    field. The two source images live in seed_assets/ alongside this file
    and are copied into Config.UPLOADS_DIR under fresh random filenames —
    the same storage convention new_contact/edit_contact use for a
    user-uploaded image (see blueprints/contacts.py's _save_image_upload).

    Idempotent: does nothing if a contact by this name already exists for
    the tenant (whether left over from an earlier run of this function, or
    a real contact the user happens to have named the same thing), so it's
    safe to call from both a brand-new tenant's seed_first_tenant() and
    the schema-migration path for an already-running tenant (db.py's
    _migration_contact_business_card)."""
    import os
    import shutil
    import uuid

    from config import Config

    existing = db.execute(
        "SELECT 1 FROM contacts WHERE tenant_id = ? AND full_name = ?",
        (tenant_id, "Gallant Plumbing Services"),
    ).fetchone()
    if existing:
        return

    assets_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seed_assets")
    front_src = os.path.join(assets_dir, "gallant_plumbing_card_front.jpg")
    back_src = os.path.join(assets_dir, "gallant_plumbing_card_back.jpg")
    if not (os.path.exists(front_src) and os.path.exists(back_src)):
        return  # seed_assets not shipped in this build - skip rather than fail

    front_filename = f"{uuid.uuid4().hex}.jpg"
    back_filename = f"{uuid.uuid4().hex}.jpg"
    shutil.copyfile(front_src, os.path.join(Config.UPLOADS_DIR, front_filename))
    shutil.copyfile(back_src, os.path.join(Config.UPLOADS_DIR, back_filename))

    vendor_context = db.execute(
        "SELECT contact_context_id FROM contact_contexts WHERE tenant_id = ? AND code = 'VENDOR'",
        (tenant_id,),
    ).fetchone()

    db.execute(
        """INSERT INTO contacts
           (tenant_id, full_name, file_as, context_id, business_card_front_path, business_card_back_path, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            tenant_id, "Gallant Plumbing Services", "Gallant Plumbing Services",
            vendor_context["contact_context_id"] if vendor_context else None,
            front_filename, back_filename,
            "Sample record demonstrating the Business Card field (front + back, click the card to flip) — "
            "edit or delete freely.",
        ),
    )
    db.commit()


def seed_first_tenant(db):
    """Initial data: the first tenant ("Acme Corp") with its Tenant Admin
    (username 'Zeb', password 'Zebra' — change this after first login),
    its own set of lookup tables, and the shared global geography tables.
    Safe to re-run: does nothing if this tenant already exists.

    Called by `flask --app app seed-tenant`. This is how GSS gets its
    first working login without anyone needing to go through the /setup
    wizard (which still exists, for provisioning additional tenants
    later).
    """
    from security import crypto
    from security.passwords import hash_password
    from security.wordlist import generate_seed_phrase, hash_phrase

    existing = db.execute("SELECT tenant_id FROM tenants WHERE tenant_code = ?", ("ACME_CORP",)).fetchone()
    if existing:
        return existing["tenant_id"]

    dek = crypto.new_tenant_dek()
    dek_wrapped = crypto.wrap_tenant_dek(dek)
    cur = db.execute(
        "INSERT INTO tenants (tenant_code, tenant_name, dek_wrapped) VALUES (?, ?, ?)",
        ("ACME_CORP", "Acme Corp", dek_wrapped),
    )
    tenant_id = cur.lastrowid

    # Recovery seed phrase is generated but not surfaced anywhere for this
    # CLI-seeded admin (there's no UI moment to show it, unlike the /setup
    # wizard's one-time reveal page). Recorded as a hash only, same as
    # everywhere else; the plaintext is discarded immediately. Use "forgot
    # password" if a real recovery phrase is needed later.
    seed_phrase = generate_seed_phrase()
    db.execute(
        """INSERT INTO users (tenant_id, username, display_name, password_hash, role, recovery_seed_hash)
           VALUES (?, 'Zeb', 'Zeb', ?, 'TenantAdmin', ?)""",
        (tenant_id, hash_password("Zebra"), hash_phrase(seed_phrase)),
    )
    db.commit()

    seed_lookup_tables(db, tenant_id)
    seed_business_card_sample_contact(db, tenant_id)

    db.execute(
        "INSERT INTO audit_log (tenant_id, action, entity_type, entity_id, detail) VALUES (?, 'Setup', 'tenants', ?, ?)",
        (tenant_id, tenant_id, "Seeded Acme Corp tenant with admin user 'Zeb' via seed-tenant CLI command"),
    )
    db.commit()
    return tenant_id
