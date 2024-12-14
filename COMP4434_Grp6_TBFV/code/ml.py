import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.model_selection import train_test_split, KFold
from sklearn.svm import SVC
from sklearn.metrics import accuracy_score
import re
from sklearn.linear_model import Lasso, LogisticRegression
import numpy as np
from sklearn.tree import DecisionTreeClassifier
from gensim.models import Word2Vec
import torch

# Load the TSV data
data_path = '../dataset/tsv_data_horizontal/train.tsv'
data = pd.read_csv(data_path, sep='\t', header=None).values
# Load data for BERT-extracted feature
statement_features_path = r"../dataset/bert_feature_data/statement_features_train.npy"
table_features_path = r"../dataset/bert_feature_data/table_feature_train.npy"
labels_path = r"../dataset/bert_feature_data/labels_train.npy"

#-----------------Data Preprocessing-----------------
# Clean 'row x is:' in table
def clean_out_sub_table(tsv_data):
    #table_texts_first = [" ".join(row[3:-2]) for row in tsv_data]
    table_texts_first = []
    for row in tsv_data:
        row[3] = re.sub(r'\(.*?\)','',str(row[3]))
        if row[3] != 'nan':
            table_texts_first.append(" ".join(row[2:-2]))
        else:
            table_texts_first.append(row[2])
    table_texts_second = [re.sub(r'\. (.*?) :', ',', row) for row in table_texts_first]
    # print(table_texts_second[0])
    table_texts_final = []

    for row in table_texts_second:
        intermediate = row.split(" : ")
        if len(intermediate) > 1:
            table_texts_final.append(intermediate[1])
        else:
            table_texts_final.append(intermediate[0])

    return table_texts_final

# Convert data into required format
def preprocess_tsv_data(tsv_data):
    # Concatenate table-related columns into a single string for each row
    # Starting from column 3
    table_texts = clean_out_sub_table(tsv_data)
    statements = tsv_data[:, -2]
    labels = tsv_data[:, -1].astype(int)
    return table_texts, statements, labels

# Preprocess the TSV data
table_texts, statements, labels = preprocess_tsv_data(data)

# Print a sample test case
print("Sample table text:", table_texts[0])
print("Sample statement:", statements[0])
print("Sample label:", labels[0])

#-----------------TF-IDF Feature Extraction -----------------
vectorizer = TfidfVectorizer(max_features=500)
table_features = vectorizer.fit_transform(table_texts)
statement_features = vectorizer.transform(statements)

#---------------Data Processing for BERT-extracted features--------------
# Load data from npy file
bert_statement_features  = np.load(statement_features_path)
bert_table_features = np.load(table_features_path)
bert_labels = np.load(labels_path,allow_pickle=True)

# Convert numpy array to tensor
table_features_tensor = torch.from_numpy(bert_table_features)
statement_features_tensor = torch.from_numpy(bert_statement_features)

# Reshape both features
statement_features_reshape = statement_features_tensor.reshape(360932,-1)
table_features_reshape = table_features_tensor.reshape(360932,-1)


#-----------------Cosine Similarity Calculation-----------------
# Combine features by calculating similarity
similarities = cosine_similarity(table_features, statement_features)


#-----------------Post Cosine Similarity Data Processing for BERT-extracted Features--------------
#Convert the tensor back to numpy array again
# Calculate Cosine similarity of table and statement after reshaping for BERT-extracted features
cos_1 = torch.nn.CosineSimilarity(dim=1)
output1 = cos_1(statement_features_reshape,table_features_reshape)
numpy_cosine_sim = output1.numpy()

# Concatenate feature after cosine-similarity calculate with labels
stacked = np.vstack((numpy_cosine_sim, labels))  # Transpose to get the desired shape

# Convert to the desired structure
dataset = stacked.T  # Transpose back to get the final result


# -----------------Word2Vec Embedding Training-----------------
# Preprocess table_texts and statements into tokenized lists
tokenized_table_texts = [text.split() for text in table_texts]
tokenized_statements = [text.split() for text in statements]

# Train a Word2Vec model
w2v_model = Word2Vec(sentences=tokenized_table_texts + tokenized_statements, vector_size=50, window=5, min_count=1, workers=4)


# -----------------Feature Extraction with Word2Vec-----------------
def get_average_word2vec(texts, model, vector_size):
    """
    Convert each text into a vector by averaging the Word2Vec embeddings of its words.

    Parameters:
    texts: List of tokenized texts.
    model: Trained Word2Vec model.
    vector_size: Size of the word embeddings.

    Returns:
    Array of vectors representing each text.
    """
    features = np.zeros((len(texts), vector_size))
    for i, tokens in enumerate(texts):
        word_vectors = [model.wv[word] for word in tokens if word in model.wv]
        if word_vectors:
            features[i] = np.mean(word_vectors, axis=0)  # Average embeddings
    return features

# Generate Word2Vec features for tables and statements
table_features_w2v = get_average_word2vec(tokenized_table_texts, w2v_model, vector_size=50)
statement_features_w2v = get_average_word2vec(tokenized_statements, w2v_model, vector_size=50)

# -----------------Feature Combination-----------------
# Combine table and statement features
similarities = np.hstack([table_features_w2v, statement_features_w2v])


#-----------------Prepare training and testing data-----------------
# Prepare training and testing data
X_train, X_test, y_train, y_test = train_test_split(similarities, labels, test_size=0.2, random_state=42)


#-----------------Cross-Validation Function-----------------
def cross_validate_model(model, X, y, k=5, is_regression=False):
    """
    Perform K-Fold Cross-Validation for a given model.

    Parameters:
    model: The machine learning model (e.g., LogisticRegression, Lasso, SVC).
    X: Feature matrix.
    y: Labels.
    k: Number of folds (default is 5).
    is_regression: Whether the model is a regression model (default is False).

    Returns:
    average_accuracy: The average accuracy across all folds.
    """
    kf = KFold(n_splits=k, shuffle=True, random_state=42)
    accuracies = []

    for train_index, test_index in kf.split(X):
        X_train, X_test = X[train_index], X[test_index]
        y_train, y_test = y[train_index], y[test_index]

        model.fit(X_train, y_train)  # Train the model
        y_pred = model.predict(X_test)  # Predict on test data

        # If regression, convert predictions to discrete labels
        if is_regression:
            y_pred = np.round(y_pred).astype(int)

        accuracy = accuracy_score(y_test, y_pred)
        accuracies.append(accuracy)
        print(f"Fold Accuracy: {accuracy:.2f}")

    average_accuracy = sum(accuracies) / k
    return average_accuracy


#-----------------Lasso Regression-----------------
# Train a Lasso Regression model
print("\nLasso Regression Cross-Validation:")
lasso_model = Lasso(alpha=0.1)
lasso_avg_accuracy = cross_validate_model(lasso_model, similarities, labels, k=5, is_regression=True)
print(f"Average Accuracy for Lasso Regression: {lasso_avg_accuracy:.2f}")


# #-----------------Support Vector Machine-----------------
# print("\nSupport Vector Machine Cross-Validation:")
# svm_model = SVC(kernel='linear')
# svm_avg_accuracy = cross_validate_model(svm_model, similarities, labels, k=5)
# print(f"Average Accuracy for Support Vector Machine: {svm_avg_accuracy:.2f}")
#
#
# #-----------------Decision Tree Classifier-----------------
# print("\nDecision Tree Classifier Cross-Validation:")
# dt_model = DecisionTreeClassifier()
# dt_avg_accuracy = cross_validate_model(dt_model, similarities, labels, k=5)
# print(f"Average Accuracy for Decision Tree Classifier: {dt_avg_accuracy:.2f}")
#
#
#-----------------BERT-extracted Feature Logistic Regression------------

# Separate features and labels
X = dataset[:, :-1]  # Features - all rows, all columns except the last
y = dataset[:, -1].astype(int).reshape(-1)   # Labels - all rows, only the last column

#-----------------Logistic Regression Classifier-----------------
clf = LogisticRegression(max_iter = 1000)
lg_avg_accuracy = cross_validate_model(clf, X, y, k=5, is_regression=True)
print(f"Average Accuracy for Logistic Regression Classifier: {lg_avg_accuracy:.2f}")
