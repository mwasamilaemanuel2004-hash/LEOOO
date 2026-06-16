## 2024-06-15 - Vectorization for Pattern Matching
**Learning:** Python loops for similarity search (cosine similarity) become a major bottleneck as the number of patterns grows (e.g., 2000+). Vectorizing these operations with NumPy matrix multiplication provides a ~10x-50x speedup.
**Action:** Always prefer NumPy vectorized operations over `for` loops when dealing with feature vector comparisons or distance metrics in AI/ML components.
