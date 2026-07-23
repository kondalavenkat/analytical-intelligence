from typing import Dict, Any, Callable
import pandas as pd
import numpy as np

class OperationRegistry:
    """
    Registry for deterministic data operations.
    Abstracts the execution engine (Pandas initially, could be DuckDB/Polars later).
    """
    
    def __init__(self):
        self._operations: Dict[str, Callable] = {}
        self._register_default_pandas_operations()
        
    def register(self, name: str, func: Callable):
        self._operations[name] = func
        
    def get_supported_operations(self) -> list[str]:
        return list(self._operations.keys())
        
    def execute(self, plan: Dict[str, Any], df: pd.DataFrame) -> Dict[str, Any]:
        op_name = plan.get("operation")
        if not op_name:
            return {"error": "No operation specified in plan.", "unsupported": True}
            
        if op_name not in self._operations:
            return {"error": f"Operation '{op_name}' is not supported yet.", "unsupported": True}
            
        import time
        import uuid
        t0 = time.time()
        try:
            result = self._operations[op_name](plan, df)
            
            # Inject rich ExecutionMetadata
            if "error" not in result:
                res_df = result.get("result_df")
                base_meta = result.get("metadata", {})
                
                result["metadata"] = {
                    "execution_id": str(uuid.uuid4()),
                    "registry_operation": op_name,
                    "execution_time_ms": round((time.time() - t0) * 1000, 2),
                    "rows_in": len(df),
                    "rows_out": len(res_df) if res_df is not None and isinstance(res_df, pd.DataFrame) else (1 if res_df is not None else 0),
                    "columns_used": base_meta.get("columns_used", []),
                    "aggregation": plan.get("aggregation"),
                    "sort": plan.get("sort"),
                    "confidence": plan.get("confidence", {}).get("overall"),
                    "warnings": [],
                    "chart": plan.get("chart"),
                    "version": "2.3"
                }
                
            return result
        except Exception as e:
            return {"error": f"Execution failed: {str(e)}"}
            
    # --- Pandas Implementations ---

    def _register_default_pandas_operations(self):
        self.register("groupby_sum", self._execute_groupby_sum)
        self.register("groupby_mean", self._execute_groupby_mean)
        self.register("groupby_count", self._execute_groupby_count)
        self.register("groupby_max", self._execute_groupby_max)
        self.register("groupby_min", self._execute_groupby_min)
        self.register("count", self._execute_count)
        self.register("filter", self._execute_filter)
        self.register("sort", self._execute_sort)
        self.register("top_n", self._execute_top_n)
        self.register("distinct", self._execute_distinct)
        self.register("value_counts", self._execute_value_counts)
        self.register("describe", self._execute_describe)
        self.register("null_summary", self._execute_null_summary)
        self.register("duplicate_summary", self._execute_duplicate_summary)
        self.register("direct_qa", self._execute_direct_qa)
        
    def _execute_groupby_sum(self, plan: Dict[str, Any], df: pd.DataFrame) -> Dict[str, Any]:
        group_by = plan.get("group_by")
        value = plan.get("value")
        limit = plan.get("limit", 10)
        
        if not group_by or not value:
            raise ValueError("groupby_sum requires 'group_by' and 'value' columns")
            
        res = df.groupby(group_by, as_index=False)[value].sum()
        res = res.sort_values(by=value, ascending=False).head(limit)
        
        chart_data = {
            "type": "bar",
            "labels": res[group_by].astype(str).tolist(),
            "datasets": [{"label": value, "data": res[value].tolist()}]
        }
        
        return {
            "result_df": res,
            "chart_data": chart_data,
            "metadata": {
                "operation": "groupby_sum",
                "rows_processed": len(df),
                "columns_used": [group_by, value]
            }
        }
        
    def _execute_groupby_mean(self, plan: Dict[str, Any], df: pd.DataFrame) -> Dict[str, Any]:
        group_by = plan.get("group_by")
        value = plan.get("value")
        limit = plan.get("limit", 10)
        
        if not group_by or not value:
            raise ValueError("groupby_mean requires 'group_by' and 'value' columns")
            
        res = df.groupby(group_by, as_index=False)[value].mean()
        res = res.sort_values(by=value, ascending=False).head(limit)
        
        return {
            "result_df": res,
            "chart_data": {
                "type": "bar",
                "labels": res[group_by].astype(str).tolist(),
                "datasets": [{"label": f"Avg {value}", "data": res[value].tolist()}]
            },
            "metadata": {"operation": "groupby_mean", "rows_processed": len(df), "columns_used": [group_by, value]}
        }

    def _execute_groupby_count(self, plan: Dict[str, Any], df: pd.DataFrame) -> Dict[str, Any]:
        group_by = plan.get("group_by")
        limit = plan.get("limit", 10)
        
        if not group_by:
            raise ValueError("groupby_count requires 'group_by' column")
            
        res = df.groupby(group_by).size().reset_index(name="Count")
        res = res.sort_values(by="Count", ascending=False).head(limit)
        
        return {
            "result_df": res,
            "chart_data": {
                "type": "bar",
                "labels": res[group_by].astype(str).tolist(),
                "datasets": [{"label": "Count", "data": res["Count"].tolist()}]
            },
            "metadata": {"operation": "groupby_count", "rows_processed": len(df), "columns_used": [group_by]}
        }

    def _execute_groupby_max(self, plan: Dict[str, Any], df: pd.DataFrame) -> Dict[str, Any]:
        group_by = plan.get("group_by")
        value = plan.get("value")
        limit = plan.get("limit", 10)
        if not group_by or not value: raise ValueError("Requires 'group_by' and 'value'")
        res = df.groupby(group_by, as_index=False)[value].max().sort_values(by=value, ascending=False).head(limit)
        return {"result_df": res, "metadata": {"operation": "groupby_max", "rows_processed": len(df), "columns_used": [group_by, value]}}

    def _execute_groupby_min(self, plan: Dict[str, Any], df: pd.DataFrame) -> Dict[str, Any]:
        group_by = plan.get("group_by")
        value = plan.get("value")
        limit = plan.get("limit", 10)
        if not group_by or not value: raise ValueError("Requires 'group_by' and 'value'")
        res = df.groupby(group_by, as_index=False)[value].min().sort_values(by=value, ascending=True).head(limit)
        return {"result_df": res, "metadata": {"operation": "groupby_min", "rows_processed": len(df), "columns_used": [group_by, value]}}

    def _execute_count(self, plan: Dict[str, Any], df: pd.DataFrame) -> Dict[str, Any]:
        res = pd.DataFrame([{"Total Rows": len(df)}])
        return {"result_df": res, "metadata": {"operation": "count", "rows_processed": len(df), "columns_used": []}}
        
    def _execute_filter(self, plan: Dict[str, Any], df: pd.DataFrame) -> Dict[str, Any]:
        # column can come as 'column' or 'group_by' (fallback)
        column = plan.get("column") or plan.get("group_by")
        # filter value can come as 'filter_value' or 'value'
        value = plan.get("filter_value") or plan.get("value")
        limit = plan.get("limit", 50)
        if not column or value is None:
            raise ValueError("filter requires a column and a filter value")
        
        res = df[df[column].astype(str).str.contains(str(value), case=False, na=False)]
        return {
            "result_df": res.head(limit), 
            "metadata": {"operation": "filter", "rows_processed": len(df), "columns_used": [column]}
        }
        
    def _execute_sort(self, plan: Dict[str, Any], df: pd.DataFrame) -> Dict[str, Any]:
        column = plan.get("column") or plan.get("value") or plan.get("group_by")
        ascending = plan.get("ascending", False)
        limit = plan.get("limit", 50)
        if not column: raise ValueError("sort requires 'column' or 'value'")
        res = df.sort_values(by=column, ascending=ascending).head(limit)
        return {"result_df": res, "metadata": {"operation": "sort", "rows_processed": len(df), "columns_used": [column]}}
        
    def _execute_top_n(self, plan: Dict[str, Any], df: pd.DataFrame) -> Dict[str, Any]:
        column = plan.get("column") or plan.get("value")
        limit = plan.get("limit", 10)
        if not column: raise ValueError("top_n requires 'column' or 'value'")
        res = df.sort_values(by=column, ascending=False).head(limit)
        return {"result_df": res, "metadata": {"operation": "top_n", "rows_processed": len(df), "columns_used": [column]}}

    def _execute_distinct(self, plan: Dict[str, Any], df: pd.DataFrame) -> Dict[str, Any]:
        column = plan.get("column") or plan.get("group_by")
        if not column: raise ValueError("distinct requires 'column' or 'group_by'")
        res = pd.DataFrame({column: df[column].dropna().unique()})
        return {"result_df": res.head(50), "metadata": {"operation": "distinct", "rows_processed": len(df), "columns_used": [column]}}

    def _execute_value_counts(self, plan: Dict[str, Any], df: pd.DataFrame) -> Dict[str, Any]:
        column = plan.get("column") or plan.get("group_by")
        limit = plan.get("limit", 10)
        if not column: raise ValueError("value_counts requires 'column' or 'group_by'")
        res = df[column].value_counts().reset_index()
        res.columns = [column, "Count"]
        res = res.head(limit)
        chart_data = {
            "type": "pie",
            "labels": res[column].astype(str).tolist(),
            "datasets": [{"label": "Count", "data": res["Count"].tolist()}]
        }
        return {"result_df": res, "chart_data": chart_data, "metadata": {"operation": "value_counts", "rows_processed": len(df), "columns_used": [column]}}
        
    def _execute_describe(self, plan: Dict[str, Any], df: pd.DataFrame) -> Dict[str, Any]:
        res = df.describe(include="all").reset_index()
        return {"result_df": res, "metadata": {"operation": "describe", "rows_processed": len(df), "columns_used": list(df.columns)}}

    def _execute_null_summary(self, plan: Dict[str, Any], df: pd.DataFrame) -> Dict[str, Any]:
        nulls = df.isnull().sum()
        res = pd.DataFrame({"Column": nulls.index, "Missing_Values": nulls.values})
        res = res[res["Missing_Values"] > 0].sort_values(by="Missing_Values", ascending=False)
        return {"result_df": res, "metadata": {"operation": "null_summary", "rows_processed": len(df), "columns_used": []}}
        
    def _execute_duplicate_summary(self, plan: Dict[str, Any], df: pd.DataFrame) -> Dict[str, Any]:
        dupes = df.duplicated().sum()
        res = pd.DataFrame([{"Total_Duplicates": dupes}])
        return {"result_df": res, "metadata": {"operation": "duplicate_summary", "rows_processed": len(df), "columns_used": []}}

    def _execute_direct_qa(self, plan: Dict[str, Any], df: pd.DataFrame) -> Dict[str, Any]:
        # Fallback for asking about meaning rather than math
        return {"result_df": df.head(10), "metadata": {"operation": "direct_qa", "rows_processed": len(df), "columns_used": []}}

# Singleton instance
operation_registry = OperationRegistry()
