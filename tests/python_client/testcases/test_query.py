import pytest
import random
import numpy as np
import pandas as pd
from pymilvus import DefaultConfig
import threading

from base.client_base import TestcaseBase
from common.code_mapping import ConnectionErrorMessage as cem
from common.code_mapping import CollectionErrorMessage as clem
from common import common_func as cf
from common import common_type as ct
from common.common_type import CaseLabel, CheckTasks
from utils.util_log import test_log as log
import utils.util_pymilvus as ut

prefix = "query"
exp_res = "exp_res"
default_term_expr = f'{ct.default_int64_field_name} in [0, 1]'
default_mix_expr = "int64 >= 0 && varchar >= \"0\""
default_invaild_expr = "varchar >= 0"
default_string_term_expr = f'{ct.default_string_field_name} in [\"0\", \"1\"]'
default_index_params = {"index_type": "IVF_SQ8", "metric_type": "L2", "params": {"nlist": 64}}
binary_index_params = {"index_type": "BIN_IVF_FLAT", "metric_type": "JACCARD", "params": {"nlist": 64}}

default_entities = ut.gen_entities(ut.default_nb, is_normal=True)
default_pos = 5
default_int_field_name = "int64"
default_float_field_name = "float"
default_string_field_name = "varchar"


class TestQueryParams(TestcaseBase):
    """
    test Query interface
    query(collection_name, expr, output_fields=None, partition_names=None, timeout=None)
    """

    @pytest.mark.tags(CaseLabel.L2)
    def test_query_invalid(self):
        """
        target: test query with invalid term expression
        method: query with invalid term expr
        expected: raise exception
        """
        collection_w, entities = self.init_collection_general(prefix, insert_data=True)[0:2]
        term_expr = f'{default_int_field_name} in {entities[:default_pos]}'
        error = {ct.err_code: 1, ct.err_msg: "unexpected token Identifier"}
        collection_w.query(term_expr, check_task=CheckTasks.err_res, check_items=error)

    @pytest.mark.tags(CaseLabel.L0)
    def test_query(self):
        """
        target: test query
        method: query with term expr
        expected: verify query result
        """
        # create collection, insert default_nb, load collection
        collection_w, vectors = self.init_collection_general(prefix, insert_data=True)[0:2]
        int_values = vectors[0][ct.default_int64_field_name].values.tolist()
        pos = 5
        term_expr = f'{ct.default_int64_field_name} in {int_values[:pos]}'
        res = vectors[0].iloc[0:pos, :1].to_dict('records')
        collection_w.query(term_expr, check_task=CheckTasks.check_query_results, check_items={exp_res: res})

    @pytest.mark.tags(CaseLabel.L1)
    def test_query_no_collection(self):
        """
        target: test the scenario which query the non-exist collection
        method: 1. create collection
                2. drop collection
                3. query the dropped collection
        expected: raise exception and report the error
        """
        # 1. initialize without data
        collection_w = self.init_collection_general(prefix)[0]
        # 2. Drop collection
        log.info("test_query_no_collection: drop collection %s" % collection_w.name)
        collection_w.drop()
        # 3. Search without collection
        log.info("test_query_no_collection: query without collection ")
        collection_w.query(default_term_expr,
                           check_task=CheckTasks.err_res,
                           check_items={"err_code": 1,
                                        "err_msg": "DescribeCollection failed: "
                                                   "can't find collection: %s" % collection_w.name})

    @pytest.mark.tags(CaseLabel.L2)
    def test_query_empty_collection(self):
        """
        target: test query empty collection
        method: query on an empty collection
        expected: empty result
        """
        c_name = cf.gen_unique_str(prefix)
        collection_w = self.init_collection_wrap(name=c_name)
        collection_w.create_index(ct.default_float_vec_field_name, index_params=ct.default_flat_index)
        collection_w.load()
        res, _ = collection_w.query(default_term_expr)
        assert len(res) == 0

    @pytest.mark.tags(CaseLabel.L0)
    def test_query_auto_id_collection(self):
        """
        target: test query with auto_id=True collection
        method: test query with auto id
        expected: query result is correct
        """
        self._connect()
        df = cf.gen_default_dataframe_data()
        df[ct.default_int64_field_name] = None
        insert_res, _, = self.collection_wrap.construct_from_dataframe(cf.gen_unique_str(prefix), df,
                                                                       primary_field=ct.default_int64_field_name,
                                                                       auto_id=True)
        assert self.collection_wrap.num_entities == ct.default_nb
        ids = insert_res[1].primary_keys
        pos = 5
        res = df.iloc[:pos, :1].to_dict('records')
        self.collection_wrap.create_index(ct.default_float_vec_field_name, index_params=ct.default_flat_index)
        self.collection_wrap.load()

        # query with all primary keys
        term_expr_1 = f'{ct.default_int64_field_name} in {ids[:pos]}'
        for i in range(5):
            res[i][ct.default_int64_field_name] = ids[i]
        self.collection_wrap.query(term_expr_1, check_task=CheckTasks.check_query_results, check_items={exp_res: res})

        # query with part primary keys
        term_expr_2 = f'{ct.default_int64_field_name} in {[ids[0], 0]}'
        self.collection_wrap.query(term_expr_2, check_task=CheckTasks.check_query_results,
                                   check_items={exp_res: res[:1]})

    @pytest.mark.tags(CaseLabel.L1)
    @pytest.mark.parametrize("dup_times", [1, 2, 3])
    @pytest.mark.parametrize("dim", [8, 128])
    def test_query_with_dup_primary_key(self, dim, dup_times):
        """
        target: test query with duplicate primary key
        method: 1.insert same data twice
                2.search
        expected: query results are de-duplicated
        """
        nb = ct.default_nb
        collection_w, insert_data, _, _ = self.init_collection_general(prefix, True, nb, dim=dim)[0:4]
        # insert dup data multi times
        for i in range(dup_times):
            collection_w.insert(insert_data[0])
        # query
        res, _ = collection_w.query(default_term_expr)
        # assert that query results are de-duplicated
        res = [m["int64"] for m in res]
        assert sorted(list(set(res))) == sorted(res)

    @pytest.mark.tags(CaseLabel.L2)
    def test_query_auto_id_not_existed_primary_values(self):
        """
        target: test query on auto_id true collection
        method: 1.create auto_id true collection
                2.query with not existed primary keys
        expected: query result is empty
        """
        schema = cf.gen_default_collection_schema(auto_id=True)
        collection_w = self.init_collection_wrap(name=cf.gen_unique_str(prefix), schema=schema)
        df = cf.gen_default_dataframe_data(ct.default_nb)
        df.drop(ct.default_int64_field_name, axis=1, inplace=True)
        mutation_res, _ = collection_w.insert(data=df)
        assert collection_w.num_entities == ct.default_nb
        collection_w.create_index(ct.default_float_vec_field_name, index_params=ct.default_flat_index)
        collection_w.load()
        term_expr = f'{ct.default_int64_field_name} in [0, 1, 2]'
        res, _ = collection_w.query(term_expr)
        assert len(res) == 0

    @pytest.mark.tags(CaseLabel.L2)
    def test_query_expr_none(self):
        """
        target: test query with none expr
        method: query with expr None
        expected: raise exception
        """
        collection_w, vectors = self.init_collection_general(prefix, insert_data=True)[0:2]
        error = {ct.err_code: 0, ct.err_msg: "The type of expr must be string"}
        collection_w.query(None, check_task=CheckTasks.err_res, check_items=error)

    @pytest.mark.tags(CaseLabel.L2)
    def test_query_non_string_expr(self):
        """
        target: test query with non-string expr
        method: query with non-string expr, eg 1, [] ..
        expected: raise exception
        """
        collection_w, vectors = self.init_collection_general(prefix, insert_data=True)[0:2]
        exprs = [1, 2., [], {}, ()]
        error = {ct.err_code: 0, ct.err_msg: "The type of expr must be string"}
        for expr in exprs:
            collection_w.query(expr, check_task=CheckTasks.err_res, check_items=error)

    @pytest.mark.tags(CaseLabel.L2)
    def test_query_expr_invalid_string(self):
        """
        target: test query with invalid expr
        method: query with invalid string expr
        expected: raise exception
        """
        collection_w, vectors = self.init_collection_general(prefix, insert_data=True)[0:2]
        error = {ct.err_code: 1, ct.err_msg: "Invalid expression!"}
        exprs = ["12-s", "中文", "a", " "]
        for expr in exprs:
            collection_w.query(expr, check_task=CheckTasks.err_res, check_items=error)

    @pytest.mark.tags(CaseLabel.L1)
    @pytest.mark.skip(reason="repeat with test_query, waiting for other expr")
    def test_query_expr_term(self):
        """
        target: test query with TermExpr
        method: query with TermExpr
        expected: query result is correct
        """
        collection_w, vectors = self.init_collection_general(prefix, insert_data=True)[0:2]
        res = vectors[0].iloc[:2, :1].to_dict('records')
        collection_w.query(default_term_expr, check_task=CheckTasks.check_query_results, check_items={exp_res: res})

    @pytest.mark.tags(CaseLabel.L2)
    def test_query_expr_not_existed_field(self):
        """
        target: test query with not existed field
        method: query by term expr with fake field
        expected: raise exception
        """
        collection_w = self.init_collection_wrap(cf.gen_unique_str(prefix))
        term_expr = 'field in [1, 2]'
        error = {ct.err_code: 1, ct.err_msg: "fieldName(field) not found"}
        collection_w.query(term_expr, check_task=CheckTasks.err_res, check_items=error)

    @pytest.mark.tags(CaseLabel.L2)
    def test_query_expr_non_primary_fields(self):
        """
        target: test query on non-primary non-vector fields
        method: query on non-primary non-vector fields
        expected: verify query result
        """
        self._connect()
        # construct dataframe and inert data
        df = pd.DataFrame({
            ct.default_int64_field_name: pd.Series(data=[i for i in range(ct.default_nb)]),
            ct.default_int32_field_name: pd.Series(data=[np.int32(i) for i in range(ct.default_nb)], dtype="int32"),
            ct.default_int16_field_name: pd.Series(data=[np.int16(i) for i in range(ct.default_nb)], dtype="int16"),
            ct.default_float_field_name: pd.Series(data=[np.float32(i) for i in range(ct.default_nb)], dtype="float32"),
            ct.default_double_field_name: pd.Series(data=[np.double(i) for i in range(ct.default_nb)], dtype="double"),
            ct.default_string_field_name: pd.Series(data=[str(i) for i in range(ct.default_nb)], dtype="string"),
            ct.default_float_vec_field_name: cf.gen_vectors(ct.default_nb, ct.default_dim)
        })
        self.collection_wrap.construct_from_dataframe(cf.gen_unique_str(prefix), df,
                                                      primary_field=ct.default_int64_field_name)
        assert self.collection_wrap.num_entities == ct.default_nb
        self.collection_wrap.create_index(ct.default_float_vec_field_name, index_params=ct.default_flat_index)
        self.collection_wrap.load()

        # query by non_primary non_vector scalar field
        non_primary_field = [ct.default_int32_field_name, ct.default_int16_field_name,
                             ct.default_float_field_name, ct.default_double_field_name, ct.default_string_field_name]

        # exp res: first two rows and all fields expect last vec field
        res = df.iloc[:2, :-1].to_dict('records')
        for field in non_primary_field:
            filter_values = df[field].tolist()[:2]
            if field is not ct.default_string_field_name:
                term_expr = f'{field} in {filter_values}'
            else:
                term_expr = f'{field} in {filter_values}'
                term_expr = term_expr.replace("'", "\"")
            self.collection_wrap.query(term_expr, output_fields=["*"],
                                       check_task=CheckTasks.check_query_results, check_items={exp_res: res})

    @pytest.mark.tags(CaseLabel.L2)
    def test_query_expr_by_bool_field(self):
        """
        target: test query by bool field and output bool field
        method: 1.create and insert with [int64, float, bool, float_vec] fields
                2.query by bool field, and output all int64, bool fields
        expected: verify query result and output fields
        """
        self._connect()
        df = cf.gen_default_dataframe_data()
        bool_values = pd.Series(data=[True if i % 2 == 0 else False for i in range(ct.default_nb)], dtype="bool")
        df.insert(2, ct.default_bool_field_name, bool_values)
        self.collection_wrap.construct_from_dataframe(cf.gen_unique_str(prefix), df,
                                                      primary_field=ct.default_int64_field_name)
        assert self.collection_wrap.num_entities == ct.default_nb
        self.collection_wrap.create_index(ct.default_float_vec_field_name, index_params=ct.default_flat_index)
        self.collection_wrap.load()

        # output bool field
        res, _ = self.collection_wrap.query(default_term_expr, output_fields=[ct.default_bool_field_name])
        assert set(res[0].keys()) == {ct.default_int64_field_name, ct.default_bool_field_name}

        # not support filter bool field with expr 'bool in [0/ 1]'
        not_support_expr = f'{ct.default_bool_field_name} in [0]'
        error = {ct.err_code: 1, ct.err_msg: 'error: value \"0\" in list cannot be casted to Bool'}
        self.collection_wrap.query(not_support_expr, output_fields=[ct.default_bool_field_name],
                                   check_task=CheckTasks.err_res, check_items=error)

        # filter bool field by bool term expr
        for bool_value in [True, False]:
            exprs = [f'{ct.default_bool_field_name} in [{bool_value}]', f'{ct.default_bool_field_name} == {bool_value}']
            for expr in exprs:
                res, _ = self.collection_wrap.query(expr, output_fields=[ct.default_bool_field_name])
                assert len(res) == ct.default_nb / 2
                for _r in res:
                    assert _r[ct.default_bool_field_name] == bool_value

    @pytest.mark.tags(CaseLabel.L1)
    def test_query_expr_by_int8_field(self):
        """
        target: test query by int8 field
        method: 1.create and insert with [int64, float, int8, float_vec] fields
                2.query by int8 field, and output all scalar fields
        expected: verify query result
        """
        self._connect()
        # construct collection from dataFrame according to [int64, float, int8, float_vec]
        df = cf.gen_default_dataframe_data()
        int8_values = pd.Series(data=[np.int8(i) for i in range(ct.default_nb)], dtype="int8")
        df.insert(2, ct.default_int8_field_name, int8_values)
        self.collection_wrap.construct_from_dataframe(cf.gen_unique_str(prefix), df,
                                                      primary_field=ct.default_int64_field_name)
        assert self.collection_wrap.num_entities == ct.default_nb
        # query expression
        term_expr = f'{ct.default_int8_field_name} in {[0]}'
        # expected query result
        res = []
        # int8 range [-128, 127] so when nb=1200, there are many repeated int8 values equal to 0
        for i in range(0, ct.default_nb, 256):
            res.extend(df.iloc[i:i + 1, :-1].to_dict('records'))
        self.collection_wrap.create_index(ct.default_float_vec_field_name, index_params=ct.default_flat_index)
        self.collection_wrap.load()
        self.collection_wrap.query(term_expr, output_fields=["*"],
                                   check_task=CheckTasks.check_query_results, check_items={exp_res: res})

    @pytest.fixture(scope="function", params=cf.gen_normal_expressions())
    def get_normal_expr(self, request):
        if request.param == "":
            pytest.skip("query with "" expr is invalid")
        yield request.param

    @pytest.mark.tags(CaseLabel.L1)
    def test_query_with_expression(self, get_normal_expr):
        """
        target: test query with different expr
        method: query with different boolean expr
        expected: verify query result
        """
        # 1. initialize with data
        nb = 1000
        collection_w, _vectors, _, insert_ids = self.init_collection_general(prefix, True, nb)[0:4]

        # filter result with expression in collection
        _vectors = _vectors[0]
        expr = get_normal_expr
        expression = expr.replace("&&", "and").replace("||", "or")
        filter_ids = []
        for i, _id in enumerate(insert_ids):
            int64 = _vectors.int64[i]
            float = _vectors.float[i]
            if not expression or eval(expression):
                filter_ids.append(_id)

        # query and verify result
        res = collection_w.query(expr=expression)[0]
        query_ids = set(map(lambda x: x[ct.default_int64_field_name], res))
        assert query_ids == set(filter_ids)

    @pytest.mark.tags(CaseLabel.L2)
    def test_query_expr_wrong_term_keyword(self):
        """
        target: test query with wrong term expr keyword
        method: query with wrong keyword term expr
        expected: raise exception
        """
        collection_w, vectors = self.init_collection_general(prefix, insert_data=True)[0:2]
        expr_1 = f'{ct.default_int64_field_name} inn [1, 2]'
        error_1 = {ct.err_code: 1, ct.err_msg: f'unexpected token Identifier("inn")'}
        collection_w.query(expr_1, check_task=CheckTasks.err_res, check_items=error_1)

        expr_3 = f'{ct.default_int64_field_name} in not [1, 2]'
        error_3 = {ct.err_code: 1, ct.err_msg: 'right operand of the InExpr must be array'}
        collection_w.query(expr_3, check_task=CheckTasks.err_res, check_items=error_3)

    @pytest.mark.tags(CaseLabel.L1)
    @pytest.mark.parametrize("field", [ct.default_int64_field_name, ct.default_float_field_name])
    def test_query_expr_not_in_term(self, field):
        """
        target: test query with `not in` expr
        method: query with not in expr
        expected: verify query result
        """
        self._connect()
        df = cf.gen_default_dataframe_data()
        self.collection_wrap.construct_from_dataframe(cf.gen_unique_str(prefix), df,
                                                      primary_field=ct.default_int64_field_name)
        assert self.collection_wrap.num_entities == ct.default_nb
        self.collection_wrap.create_index(ct.default_float_vec_field_name, index_params=ct.default_flat_index)
        self.collection_wrap.load()
        values = df[field].tolist()
        pos = 100
        term_expr = f'{field} not in {values[pos:]}'
        res = df.iloc[:pos, :3].to_dict('records')
        self.collection_wrap.query(term_expr, output_fields=["*"],
                                   check_task=CheckTasks.check_query_results, check_items={exp_res: res})

    @pytest.mark.tags(CaseLabel.L1)
    @pytest.mark.parametrize("pos", [0, ct.default_nb])
    def test_query_expr_not_in_empty_and_all(self, pos):
        """
        target: test query with `not in` expr
        method: query with `not in` expr for (non)empty collection
        expected: verify query result
        """
        self._connect()
        df = cf.gen_default_dataframe_data()
        self.collection_wrap.construct_from_dataframe(cf.gen_unique_str(prefix), df,
                                                      primary_field=ct.default_int64_field_name)
        assert self.collection_wrap.num_entities == ct.default_nb
        self.collection_wrap.create_index(ct.default_float_vec_field_name, index_params=ct.default_flat_index)
        self.collection_wrap.load()
        int64_values = df[ct.default_int64_field_name].tolist()
        term_expr = f'{ct.default_int64_field_name} not in {int64_values[pos:]}'
        res = df.iloc[:pos, :1].to_dict('records')
        self.collection_wrap.query(term_expr, check_task=CheckTasks.check_query_results, check_items={exp_res: res})

    @pytest.mark.tags(CaseLabel.L1)
    def test_query_expr_random_values(self):
        """
        target: test query with random filter values
        method: query with random filter values, like [0, 2, 4, 3]
        expected: correct query result
        """
        self._connect()
        df = cf.gen_default_dataframe_data(nb=100)
        log.debug(df.head(5))
        self.collection_wrap.construct_from_dataframe(cf.gen_unique_str(prefix), df,
                                                      primary_field=ct.default_int64_field_name)
        assert self.collection_wrap.num_entities == 100
        self.collection_wrap.create_index(ct.default_float_vec_field_name, index_params=ct.default_flat_index)
        self.collection_wrap.load()

        # random_values = [random.randint(0, ct.default_nb) for _ in range(4)]
        random_values = [0, 2, 4, 3]
        term_expr = f'{ct.default_int64_field_name} in {random_values}'
        res = df.iloc[random_values, :1].to_dict('records')
        self.collection_wrap.query(term_expr, check_task=CheckTasks.check_query_results, check_items={exp_res: res})

    @pytest.mark.tags(CaseLabel.L2)
    def test_query_expr_not_in_random(self):
        """
        target: test query with fixed filter values
        method: query with fixed filter values
        expected: correct query result
        """
        self._connect()
        df = cf.gen_default_dataframe_data(nb=50)
        log.debug(df.head(5))
        self.collection_wrap.construct_from_dataframe(cf.gen_unique_str(prefix), df,
                                                      primary_field=ct.default_int64_field_name)
        assert self.collection_wrap.num_entities == 50
        self.collection_wrap.create_index(ct.default_float_vec_field_name, index_params=ct.default_flat_index)
        self.collection_wrap.load()

        random_values = [i for i in range(10, 50)]
        log.debug(f'random values: {random_values}')
        random.shuffle(random_values)
        term_expr = f'{ct.default_int64_field_name} not in {random_values}'
        res = df.iloc[:10, :1].to_dict('records')
        self.collection_wrap.query(term_expr, check_task=CheckTasks.check_query_results, check_items={exp_res: res})

    @pytest.mark.tags(CaseLabel.L2)
    def test_query_expr_non_array_term(self):
        """
        target: test query with non-array term expr
        method: query with non-array term expr
        expected: raise exception
        """
        exprs = [f'{ct.default_int64_field_name} in 1',
                 f'{ct.default_int64_field_name} in "in"',
                 f'{ct.default_int64_field_name} in (mn)']
        collection_w, vectors = self.init_collection_general(prefix, insert_data=True)[0:2]
        error = {ct.err_code: 1, ct.err_msg: "right operand of the InExpr must be array"}
        for expr in exprs:
            collection_w.query(expr, check_task=CheckTasks.err_res, check_items=error)

    @pytest.mark.tags(CaseLabel.L2)
    def test_query_expr_empty_term_array(self):
        """
        target: test query with empty array term expr
        method: query with empty term expr
        expected: empty result
        """
        term_expr = f'{ct.default_int64_field_name} in []'
        collection_w, vectors = self.init_collection_general(prefix, insert_data=True)[0:2]
        res, _ = collection_w.query(term_expr)
        assert len(res) == 0

    @pytest.mark.tags(CaseLabel.L2)
    def test_query_expr_inconsistent_mix_term_array(self):
        """
        target: test query with term expr that field and array are inconsistent or mix type
        method: 1.query with int field and float values
                2.query with term expr that has int and float type value
        expected: raise exception
        """
        collection_w = self.init_collection_wrap(cf.gen_unique_str(prefix))
        int_values = [[1., 2.], [1, 2.]]
        error = {ct.err_code: 1, ct.err_msg: "type mismatch"}
        for values in int_values:
            term_expr = f'{ct.default_int64_field_name} in {values}'
            collection_w.query(term_expr, check_task=CheckTasks.err_res, check_items=error)

    @pytest.mark.tags(CaseLabel.L2)
    def test_query_expr_non_constant_array_term(self):
        """
        target: test query with non-constant array term expr
        method: query with non-constant array expr
        expected: raise exception
        """
        collection_w, vectors = self.init_collection_general(prefix, insert_data=True)[0:2]
        constants = [[1], (), {}]
        error = {ct.err_code: 1, ct.err_msg: "unsupported leaf node"}
        for constant in constants:
            term_expr = f'{ct.default_int64_field_name} in [{constant}]'
            collection_w.query(term_expr, check_task=CheckTasks.err_res, check_items=error)

    @pytest.mark.tags(CaseLabel.L1)
    def test_query_output_field_none_or_empty(self):
        """
        target: test query with none and empty output field
        method: query with output field=None, field=[]
        expected: return primary field
        """
        collection_w, vectors = self.init_collection_general(prefix, insert_data=True)[0:2]
        for fields in [None, []]:
            res, _ = collection_w.query(default_term_expr, output_fields=fields)
            assert res[0].keys() == {ct.default_int64_field_name}

    @pytest.mark.tags(CaseLabel.L0)
    def test_query_output_one_field(self):
        """
        target: test query with output one field
        method: query with output one field
        expected: return one field
        """
        collection_w, vectors = self.init_collection_general(prefix, insert_data=True)[0:2]
        res, _ = collection_w.query(default_term_expr, output_fields=[ct.default_float_field_name])
        assert set(res[0].keys()) == {ct.default_int64_field_name, ct.default_float_field_name}

    @pytest.mark.tags(CaseLabel.L1)
    def test_query_output_all_fields(self):
        """
        target: test query with none output field
        method: query with output field=None
        expected: return all fields
        """
        # 1. initialize with data
        collection_w, df, _, insert_ids = self.init_collection_general(prefix, True, nb=10,
                                                                       is_all_data_type=True)[0:4]
        all_fields = [ct.default_int64_field_name, ct.default_int32_field_name, ct.default_int16_field_name,
                      ct.default_int8_field_name, ct.default_bool_field_name, ct.default_float_field_name,
                      ct.default_double_field_name, ct.default_string_field_name, ct.default_float_vec_field_name]
        res = df[0].iloc[:2].to_dict('records')
        collection_w.load()
        actual_res, _ = collection_w.query(default_term_expr, output_fields=all_fields,
                                           check_task=CheckTasks.check_query_results,
                                           check_items={exp_res: res, "with_vec": True})
        assert set(actual_res[0].keys()) == set(all_fields)

    @pytest.mark.tags(CaseLabel.L2)
    def test_query_output_float_vec_field(self):
        """
        target: test query with vec output field
        method: specify vec field as output field
        expected: return primary field and vec field
        """
        collection_w = self.init_collection_wrap(name=cf.gen_unique_str(prefix))
        df = cf.gen_default_dataframe_data()
        collection_w.insert(df)
        assert collection_w.num_entities == ct.default_nb
        fields = [[ct.default_float_vec_field_name], [ct.default_int64_field_name, ct.default_float_vec_field_name]]
        res = df.loc[:1, [ct.default_int64_field_name, ct.default_float_vec_field_name]].to_dict('records')
        collection_w.create_index(ct.default_float_vec_field_name, index_params=ct.default_flat_index)
        collection_w.load()
        for output_fields in fields:
            collection_w.query(default_term_expr, output_fields=output_fields,
                               check_task=CheckTasks.check_query_results,
                               check_items={exp_res: res, "with_vec": True})

    @pytest.mark.tags(CaseLabel.L1)
    @pytest.mark.skip(reason="https://github.com/milvus-io/milvus/issues/12680")
    @pytest.mark.parametrize("vec_fields", [[cf.gen_float_vec_field(name="float_vector1")]])
    def test_query_output_multi_float_vec_field(self, vec_fields):
        """
        target: test query and output multi float vec fields
        method: a.specify multi vec field as output
                b.specify output_fields with wildcard %
        expected: verify query result
        """
        # init collection with two float vector fields
        schema = cf.gen_schema_multi_vector_fields(vec_fields)
        collection_w = self.init_collection_wrap(name=cf.gen_unique_str(prefix), schema=schema)
        df = cf.gen_dataframe_multi_vec_fields(vec_fields=vec_fields)
        collection_w.insert(df)
        assert collection_w.num_entities == ct.default_nb

        # query with two vec output_fields
        output_fields = [ct.default_int64_field_name, ct.default_float_vec_field_name]
        for vec_field in vec_fields:
            output_fields.append(vec_field.name)
        res = df.loc[:1, output_fields].to_dict('records')
        collection_w.create_index(ct.default_float_vec_field_name, index_params=ct.default_flat_index)
        collection_w.load()
        collection_w.query(default_term_expr, output_fields=output_fields,
                           check_task=CheckTasks.check_query_results,
                           check_items={exp_res: res, "with_vec": True})

    @pytest.mark.tags(CaseLabel.L1)
    @pytest.mark.skip(reason="https://github.com/milvus-io/milvus/issues/12680")
    @pytest.mark.parametrize("vec_fields", [[cf.gen_binary_vec_field()],
                                            [cf.gen_binary_vec_field(), cf.gen_binary_vec_field("binary_vec1")]])
    def test_query_output_mix_float_binary_field(self, vec_fields):
        """
        target:  test query and output mix float and binary vec fields
        method: a.specify mix vec field as output
                b.specify output_fields with wildcard %
        expected: output binary vector and float vec
        """
        # init collection with two float vector fields
        schema = cf.gen_schema_multi_vector_fields(vec_fields)
        collection_w = self.init_collection_wrap(name=cf.gen_unique_str(prefix), schema=schema)
        df = cf.gen_dataframe_multi_vec_fields(vec_fields=vec_fields)
        collection_w.insert(df)
        assert collection_w.num_entities == ct.default_nb

        # query with two vec output_fields
        output_fields = [ct.default_int64_field_name, ct.default_float_vec_field_name]
        for vec_field in vec_fields:
            output_fields.append(vec_field.name)
        res = df.loc[:1, output_fields].to_dict('records')
        collection_w.create_index(ct.default_float_vec_field_name, index_params=ct.default_flat_index)
        collection_w.load()
        collection_w.query(default_term_expr, output_fields=output_fields,
                           check_task=CheckTasks.check_query_results,
                           check_items={exp_res: res, "with_vec": True})

        # query with wildcard %
        collection_w.query(default_term_expr, output_fields=["%"],
                           check_task=CheckTasks.check_query_results,
                           check_items={exp_res: res, "with_vec": True})

    @pytest.mark.tags(CaseLabel.L2)
    def test_query_output_binary_vec_field(self):
        """
        target: test query with binary vec output field
        method: specify binary vec field as output field
        expected: return primary field and binary vec field
        """
        collection_w, vectors = self.init_collection_general(prefix, insert_data=True, is_binary=True)[0:2]
        fields = [[ct.default_binary_vec_field_name], [ct.default_int64_field_name, ct.default_binary_vec_field_name]]
        for output_fields in fields:
            res, _ = collection_w.query(default_term_expr, output_fields=output_fields)
            assert res[0].keys() == set(fields[-1])

    @pytest.mark.tags(CaseLabel.L1)
    def test_query_output_primary_field(self):
        """
        target: test query with output field only primary field
        method: specify int64 primary field as output field
        expected: return int64 field
        """
        collection_w, vectors = self.init_collection_general(prefix, insert_data=True)[0:2]
        res, _ = collection_w.query(default_term_expr, output_fields=[ct.default_int64_field_name])
        assert res[0].keys() == {ct.default_int64_field_name}

    @pytest.mark.tags(CaseLabel.L2)
    def test_query_output_not_existed_field(self):
        """
        target: test query output not existed field
        method: query with not existed output field
        expected: raise exception
        """
        collection_w, vectors = self.init_collection_general(prefix, insert_data=True)[0:2]
        error = {ct.err_code: 1, ct.err_msg: 'Field int not exist'}
        output_fields = [["int"], [ct.default_int64_field_name, "int"]]
        for fields in output_fields:
            collection_w.query(default_term_expr, output_fields=fields, check_task=CheckTasks.err_res,
                               check_items=error)

    @pytest.mark.tags(CaseLabel.L2)
    @pytest.mark.xfail(reason="exception not MilvusException")
    def test_query_invalid_output_fields(self):
        """
        target: test query with invalid output fields
        method: query with invalid field fields
        expected: raise exception
        """
        collection_w, vectors = self.init_collection_general(prefix, insert_data=True)[0:2]
        output_fields = ["12-s", 1, [1, "2", 3], (1,), {1: 1}]
        error = {ct.err_code: 0, ct.err_msg: f'Invalid query format. \'output_fields\' must be a list'}
        for fields in output_fields:
            collection_w.query(default_term_expr, output_fields=fields, check_task=CheckTasks.err_res,
                               check_items=error)

    @pytest.mark.tags(CaseLabel.L0)
    def test_query_output_fields_simple_wildcard(self):
        """
        target: test query output_fields with simple wildcard (* and %)
        method: specify output_fields as "*" and "*", "%"
        expected: output all scale field; output all fields
        """
        # init collection with fields: int64, float, float_vec, float_vector1
        # collection_w, df = self.init_multi_fields_collection_wrap(cf.gen_unique_str(prefix))
        collection_w, vectors = self.init_collection_general(prefix, insert_data=True)[0:2]
        df = vectors[0]

        # query with wildcard scale(*)
        output_fields = [ct.default_int64_field_name, ct.default_float_field_name, ct.default_string_field_name]
        res = df.loc[:1, output_fields].to_dict('records')
        collection_w.query(default_term_expr, output_fields=["*"],
                           check_task=CheckTasks.check_query_results,
                           check_items={exp_res: res})

        # query with wildcard % output_fields2 = [ct.default_int64_field_name, ct.default_float_vec_field_name,
        # ct.another_float_vec_field_name]
        output_fields2 = [ct.default_int64_field_name, ct.default_float_vec_field_name]
        res2 = df.loc[:1, output_fields2].to_dict('records')
        collection_w.query(default_term_expr, output_fields=["%"],
                           check_task=CheckTasks.check_query_results,
                           check_items={exp_res: res2, "with_vec": True})

        # query with wildcard all fields: vector(%) and scale(*)
        res3 = df.iloc[:2].to_dict('records')
        collection_w.query(default_term_expr, output_fields=["*", "%"],
                           check_task=CheckTasks.check_query_results,
                           check_items={exp_res: res3, "with_vec": True})

    @pytest.mark.tags(CaseLabel.L1)
    def test_query_output_fields_part_scale_wildcard(self):
        """
        target: test query output_fields with part wildcard
        method: specify output_fields as wildcard and part field
        expected: verify query result
        """
        # init collection with fields: int64, float, float_vec
        collection_w, vectors = self.init_collection_general(prefix, insert_data=True, is_index=True)[0:2]
        df = vectors[0]

        # query with output_fields=["*", float_vector)
        res = df.iloc[:2, :4].to_dict('records')
        collection_w.create_index(ct.default_float_vec_field_name, index_params=ct.default_flat_index)
        collection_w.load()
        collection_w.query(default_term_expr, output_fields=["*", ct.default_float_vec_field_name],
                           check_task=CheckTasks.check_query_results,
                           check_items={exp_res: res, "with_vec": True})

        # query with output_fields=["*", float)
        res2 = df.iloc[:2, :3].to_dict('records')
        collection_w.load()
        collection_w.query(default_term_expr, output_fields=["*", ct.default_float_field_name],
                           check_task=CheckTasks.check_query_results,
                           check_items={exp_res: res2})

    @pytest.mark.tags(CaseLabel.L1)
    @pytest.mark.skip(reason="https://github.com/milvus-io/milvus/issues/12680")
    def test_query_output_fields_part_vector_wildcard(self):
        """
        target: test query output_fields with part wildcard
        method: specify output_fields as wildcard and part field
        expected: verify query result
        """
        # init collection with fields: int64, float, float_vec, float_vector1
        collection_w, df = self.init_multi_fields_collection_wrap(cf.gen_unique_str(prefix))
        collection_w.load()

        # query with output_fields=["%", float), expected: all fields
        res = df.iloc[:2].to_dict('records')
        collection_w.query(default_term_expr, output_fields=["%", ct.default_float_field_name],
                           check_task=CheckTasks.check_query_results,
                           check_items={exp_res: res, "with_vec": True})

        # query with output_fields=["%", float_vector), expected: int64, float_vector, float_vector1
        output_fields = [ct.default_int64_field_name, ct.default_float_vec_field_name, ct.another_float_vec_field_name]
        res2 = df.loc[:1, output_fields].to_dict('records')
        collection_w.query(default_term_expr, output_fields=["%", ct.default_float_vec_field_name],
                           check_task=CheckTasks.check_query_results,
                           check_items={exp_res: res2, "with_vec": True})

    @pytest.mark.tags(CaseLabel.L2)
    @pytest.mark.parametrize("output_fields", [["*%"], ["**"], ["*", "@"]])
    def test_query_invalid_wildcard(self, output_fields):
        """
        target: test query with invalid output wildcard
        method: output_fields is invalid output wildcard
        expected: raise exception
        """
        # init collection with fields: int64, float, float_vec
        collection_w = self.init_collection_general(prefix, insert_data=True, nb=100)[0]
        collection_w.load()

        # query with invalid output_fields
        error = {ct.err_code: 1, ct.err_msg: f"Field {output_fields[-1]} not exist"}
        collection_w.query(default_term_expr, output_fields=output_fields,
                           check_task=CheckTasks.err_res, check_items=error)

    @pytest.mark.tags(CaseLabel.L0)
    def test_query_partition(self):
        """
        target: test query on partition
        method: create a partition and query
        expected: verify query result
        """
        collection_w = self.init_collection_wrap(name=cf.gen_unique_str(prefix))
        partition_w = self.init_partition_wrap(collection_wrap=collection_w)
        df = cf.gen_default_dataframe_data()
        partition_w.insert(df)
        assert collection_w.num_entities == ct.default_nb
        collection_w.create_index(ct.default_float_vec_field_name, index_params=ct.default_flat_index)
        partition_w.load()
        res = df.iloc[:2, :1].to_dict('records')
        collection_w.query(default_term_expr, partition_names=[partition_w.name],
                           check_task=CheckTasks.check_query_results, check_items={exp_res: res})

    @pytest.mark.tags(CaseLabel.L2)
    def test_query_partition_without_loading(self):
        """
        target: test query on partition without loading
        method: query on partition and no loading
        expected: raise exception
        """
        collection_w = self.init_collection_wrap(name=cf.gen_unique_str(prefix))
        partition_w = self.init_partition_wrap(collection_wrap=collection_w)
        df = cf.gen_default_dataframe_data()
        partition_w.insert(df)
        assert partition_w.num_entities == ct.default_nb
        error = {ct.err_code: 1, ct.err_msg: f'collection {collection_w.name} was not loaded into memory'}
        collection_w.query(default_term_expr, partition_names=[partition_w.name],
                           check_task=CheckTasks.err_res, check_items=error)

    @pytest.mark.tags(CaseLabel.L1)
    def test_query_default_partition(self):
        """
        target: test query on default partition
        method: query on default partition
        expected: verify query result
        """
        collection_w, vectors = self.init_collection_general(prefix, insert_data=True)[0:2]
        res = vectors[0].iloc[:2, :1].to_dict('records')
        collection_w.query(default_term_expr, partition_names=[ct.default_partition_name],
                           check_task=CheckTasks.check_query_results, check_items={exp_res: res})

    @pytest.mark.tags(CaseLabel.L2)
    def test_query_empty_partition(self):
        """
        target: test query on empty partition
        method: query on an empty collection
        expected: empty query result
        """
        collection_w = self.init_collection_wrap(name=cf.gen_unique_str(prefix))
        partition_w = self.init_partition_wrap(collection_wrap=collection_w)
        assert partition_w.is_empty
        collection_w.create_index(ct.default_float_vec_field_name, index_params=ct.default_flat_index)
        partition_w.load()
        res, _ = collection_w.query(default_term_expr, partition_names=[partition_w.name])
        assert len(res) == 0

    @pytest.mark.tags(CaseLabel.L2)
    def test_query_not_existed_partition(self):
        """
        target: test query on a not existed partition
        method: query on not existed partition
        expected: raise exception
        """
        collection_w = self.init_collection_wrap(cf.gen_unique_str(prefix))
        collection_w.create_index(ct.default_float_vec_field_name, index_params=ct.default_flat_index)
        collection_w.load()
        partition_names = cf.gen_unique_str()
        error = {ct.err_code: 1, ct.err_msg: f'PartitonName: {partition_names} not found'}
        collection_w.query(default_term_expr, partition_names=[partition_names],
                           check_task=CheckTasks.err_res, check_items=error)

    @pytest.fixture(scope="function", params=[0, 10, 100])
    def offset(self, request):
        yield request.param

    @pytest.mark.tags(CaseLabel.L1)
    def test_query_pagination(self, offset):
        """
        target: test query pagination
        method: create collection and query with pagination params,
                verify if the result is ordered by primary key
        expected: query successfully and verify query result
        """
        # create collection, insert default_nb, load collection
        collection_w, vectors = self.init_collection_general(prefix, insert_data=True)[0:2]
        int_values = vectors[0][ct.default_int64_field_name].values.tolist()
        pos = 10
        term_expr = f'{ct.default_int64_field_name} in {int_values[offset: pos+offset]}'
        res = vectors[0].iloc[offset:pos+offset, :1].to_dict('records')
        query_params = {"offset": offset, "limit": 10}
        query_res = collection_w.query(term_expr, params=query_params,
                                       check_task=CheckTasks.check_query_results,
                                       check_items={exp_res: res})[0]
        key_res = [item[key] for item in query_res for key in item]
        assert key_res == int_values[offset: pos+offset]

    @pytest.mark.tags(CaseLabel.L1)
    def test_query_binary_pagination(self, offset):
        """
        target: test query binary pagination
        method: create collection and query with pagination params,
                verify if the result is ordered by primary key
        expected: query successfully and verify query result
        """
        # create collection, insert default_nb, load collection
        collection_w, vectors = self.init_collection_general(prefix, insert_data=True,
                                                             is_binary=True)[0:2]
        int_values = vectors[0][ct.default_int64_field_name].values.tolist()
        pos = 10
        term_expr = f'{ct.default_int64_field_name} in {int_values[offset: pos+offset]}'
        res = vectors[0].iloc[offset:pos+offset, :1].to_dict('records')
        query_params = {"offset": offset, "limit": 10}
        query_res = collection_w.query(term_expr, params=query_params,
                                       check_task=CheckTasks.check_query_results,
                                       check_items={exp_res: res})[0]
        key_res = [item[key] for item in query_res for key in item]
        assert key_res == int_values[offset: pos + offset]

    @pytest.mark.tags(CaseLabel.L2)
    def test_query_pagination_with_expression(self, offset, get_normal_expr):
        """
        target: test query pagination with different expression
        method: query with different expression and verify the result
        expected: query successfully
        """
        # 1. initialize with data
        nb = 1000
        collection_w, _vectors, _, insert_ids = self.init_collection_general(prefix, True, nb)[0:4]

        # filter result with expression in collection
        _vectors = _vectors[0]
        expr = get_normal_expr
        expression = expr.replace("&&", "and").replace("||", "or")
        filter_ids = []
        for i, _id in enumerate(insert_ids):
            int64 = _vectors.int64[i]
            float = _vectors.float[i]
            if not expression or eval(expression):
                filter_ids.append(_id)

        # query and verify result
        query_params = {"offset": offset, "limit": 10}
        res = collection_w.query(expr=expression, params=query_params)[0]
        key_res = [item[key] for item in res for key in item]
        assert key_res == filter_ids

    @pytest.mark.tags(CaseLabel.L2)
    def test_query_pagination_with_partition(self, offset):
        """
        target: test query pagination on partition
        method: create a partition and query with different offset
        expected: verify query result
        """
        collection_w = self.init_collection_wrap(name=cf.gen_unique_str(prefix))
        partition_w = self.init_partition_wrap(collection_wrap=collection_w)
        df = cf.gen_default_dataframe_data()
        partition_w.insert(df)
        assert collection_w.num_entities == ct.default_nb
        collection_w.create_index(ct.default_float_vec_field_name, index_params=ct.default_flat_index)
        partition_w.load()
        res = df.iloc[:2, :1].to_dict('records')
        query_params = {"offset": offset, "limit": 10}
        collection_w.query(default_term_expr, params=query_params, partition_names=[partition_w.name],
                           check_task=CheckTasks.check_query_results, check_items={exp_res: res})

    @pytest.mark.tags(CaseLabel.L2)
    def test_query_pagination_with_insert_data(self, offset):
        """
        target: test query pagination on partition
        method: create a partition and query with pagination
        expected: verify query result
        """
        collection_w = self.init_collection_wrap(name=cf.gen_unique_str(prefix))
        df = cf.gen_default_dataframe_data()
        collection_w.insert(df)
        assert collection_w.num_entities == ct.default_nb
        collection_w.create_index(ct.default_float_vec_field_name, index_params=ct.default_flat_index)
        collection_w.load()
        res = df.iloc[:2, :1].to_dict('records')
        query_params = {"offset": offset, "limit": 10}
        collection_w.query(default_term_expr, params=query_params,
                           check_task=CheckTasks.check_query_results, check_items={exp_res: res})

    @pytest.mark.tags(CaseLabel.L1)
    def test_query_pagination_without_limit(self, offset):
        """
        target: test query pagination without limit
        method: create collection and query with pagination params(only offset),
                compare the result with query without pagination params
        expected: query successfully
        """
        collection_w, vectors = self.init_collection_general(prefix, insert_data=True)[0:2]
        int_values = vectors[0][ct.default_int64_field_name].values.tolist()
        pos = 10
        term_expr = f'{ct.default_int64_field_name} in {int_values[offset: pos + offset]}'
        res = vectors[0].iloc[offset:pos + offset, :1].to_dict('records')
        query_params = {"offset": offset}
        query_res = collection_w.query(term_expr, params=query_params,
                                       check_task=CheckTasks.check_query_results,
                                       check_items={exp_res: res})[0]
        res = collection_w.query(term_expr,
                                 check_task=CheckTasks.check_query_results,
                                 check_items={exp_res: res})[0]
        assert query_res == res

    @pytest.mark.tags(CaseLabel.L2)
    @pytest.mark.parametrize("limit", ["12 s", " ", [0, 1], {2}])
    def test_query_pagination_with_invalid_limit_type(self, limit):
        """
        target: test query pagination with invalid limit type
        method: query with invalid limit tyype
        expected: raise exception
        """
        # create collection, insert default_nb, load collection
        collection_w, vectors = self.init_collection_general(prefix, insert_data=True)[0:2]
        int_values = vectors[0][ct.default_int64_field_name].values.tolist()
        pos = 10
        term_expr = f'{ct.default_int64_field_name} in {int_values[10: pos+10]}'
        collection_w.query(term_expr, offset=10, limit=limit,
                           check_task=CheckTasks.err_res,
                           check_items={ct.err_code: 1,
                                        ct.err_msg: "limit [%s] is invalid" % limit})

    @pytest.mark.tags(CaseLabel.L2)
    @pytest.mark.parametrize("limit", [-1, 67890])
    def test_query_pagination_with_invalid_limit_value(self, limit):
        """
        target: test query pagination with invalid limit value
        method: query with invalid limit value
        expected: raise exception
        """
        # create collection, insert default_nb, load collection
        collection_w, vectors = self.init_collection_general(prefix, insert_data=True)[0:2]
        int_values = vectors[0][ct.default_int64_field_name].values.tolist()
        pos = 10
        term_expr = f'{ct.default_int64_field_name} in {int_values[10: pos + 10]}'
        collection_w.query(term_expr, offset=10, limit=limit,
                           check_task=CheckTasks.err_res,
                           check_items={ct.err_code: 1,
                                        ct.err_msg: "limit [%s] is invalid, should be in range "
                                                    "[1, 16384], but got %s" % (limit, limit)})

    @pytest.mark.tags(CaseLabel.L2)
    @pytest.mark.parametrize("offset", ["12 s", " ", [0, 1], {2}])
    def test_query_pagination_with_invalid_offset_type(self, offset):
        """
        target: test query pagination with invalid offset type
        method: query with invalid offset type
        expected: raise exception
        """
        # create collection, insert default_nb, load collection
        collection_w, vectors = self.init_collection_general(prefix, insert_data=True)[0:2]
        int_values = vectors[0][ct.default_int64_field_name].values.tolist()
        pos = 10
        term_expr = f'{ct.default_int64_field_name} in {int_values[10: pos + 10]}'
        collection_w.query(term_expr, offset=offset, limit=10,
                           check_task=CheckTasks.err_res,
                           check_items={ct.err_code: 1,
                                        ct.err_msg: "offset [%s] is invalid" % offset})

    @pytest.mark.tags(CaseLabel.L2)
    @pytest.mark.parametrize("offset", [-1, 67890])
    def test_query_pagination_with_invalid_offset_value(self, offset):
        """
        target: test query pagination with invalid offset value
        method: query with invalid offset value
        expected: raise exception
        """
        # create collection, insert default_nb, load collection
        collection_w, vectors = self.init_collection_general(prefix, insert_data=True)[0:2]
        int_values = vectors[0][ct.default_int64_field_name].values.tolist()
        pos = 10
        term_expr = f'{ct.default_int64_field_name} in {int_values[10: pos + 10]}'
        collection_w.query(term_expr, offset=offset, limit=10,
                           check_task=CheckTasks.err_res,
                           check_items={ct.err_code: 1,
                                        ct.err_msg: "offset [%s] is invalid, should be in range "
                                                    "[1, 16384], but got %s" % (offset, offset)})


class TestQueryOperation(TestcaseBase):
    """
    ******************************************************************
      The following cases are used to test query interface operations
    ******************************************************************
    """

    @pytest.mark.tags(CaseLabel.L2)
    def test_query_without_connection(self):
        """
        target: test query without connection
        method: close connect and query
        expected: raise exception
        """

        # init a collection with default connection
        collection_w = self.init_collection_wrap(name=cf.gen_unique_str(prefix))

        # remove default connection
        self.connection_wrap.remove_connection(alias=DefaultConfig.DEFAULT_USING)

        # list connection to check
        self.connection_wrap.list_connections(check_task=ct.CheckTasks.ccr, check_items={ct.list_content: []})

        # query after remove default connection
        collection_w.query(default_term_expr, check_task=CheckTasks.err_res,
                           check_items={ct.err_code: 0, ct.err_msg: cem.ConnectFirst})

    @pytest.mark.tags(CaseLabel.L2)
    def test_query_without_loading(self):
        """
        target: test query without loading
        method: no loading before query
        expected: raise exception
        """

        # init a collection with default connection
        collection_name = cf.gen_unique_str(prefix)
        collection_w = self.init_collection_wrap(name=collection_name)

        # insert data to collection
        collection_w.insert(data=cf.gen_default_list_data())

        # check number of entities and that method calls the flush interface
        assert collection_w.num_entities == ct.default_nb

        # query without load
        collection_w.query(default_term_expr, check_task=CheckTasks.err_res,
                           check_items={ct.err_code: 1, ct.err_msg: clem.CollNotLoaded % collection_name})

    @pytest.mark.tags(CaseLabel.L2)
    @pytest.mark.parametrize("term_expr", [f'{ct.default_int64_field_name} in [0]'])
    def test_query_expr_single_term_array(self, term_expr):
        """
        target: test query with single array term expr
        method: query with single array value
        expected: query result is one entity
        """

        # init a collection and insert data
        collection_w, vectors, binary_raw_vectors = self.init_collection_general(prefix, insert_data=True)[0:3]

        # query the first row of data
        check_vec = vectors[0].iloc[:, [0]][0:1].to_dict('records')
        collection_w.query(term_expr, check_task=CheckTasks.check_query_results, check_items={exp_res: check_vec})

    @pytest.mark.tags(CaseLabel.L1)
    @pytest.mark.parametrize("term_expr", [f'{ct.default_int64_field_name} in [0]'])
    def test_query_binary_expr_single_term_array(self, term_expr, check_content):
        """
        target: test query with single array term expr
        method: query with single array value
        expected: query result is one entity
        """

        # init a collection and insert data
        collection_w, vectors, binary_raw_vectors = self.init_collection_general(prefix, insert_data=True,
                                                                                 is_binary=True)[0:3]

        # query the first row of data
        check_vec = vectors[0].iloc[:, [0]][0:1].to_dict('records')
        collection_w.query(term_expr, check_task=CheckTasks.check_query_results, check_items={exp_res: check_vec})

    @pytest.mark.tags(CaseLabel.L2)
    def test_query_expr_all_term_array(self):
        """
        target: test query with all array term expr
        method: query with all array value
        expected: verify query result
        """

        # init a collection and insert data
        collection_w, vectors, binary_raw_vectors = self.init_collection_general(prefix, insert_data=True)[0:3]

        # data preparation
        int_values = vectors[0][ct.default_int64_field_name].values.tolist()
        term_expr = f'{ct.default_int64_field_name} in {int_values}'
        check_vec = vectors[0].iloc[:, [0]][0:len(int_values)].to_dict('records')

        # query all array value
        collection_w.query(term_expr, check_task=CheckTasks.check_query_results, check_items={exp_res: check_vec})

    @pytest.mark.tags(CaseLabel.L1)
    def test_query_expr_half_term_array(self):
        """
        target: test query with half array term expr
        method: query with half array value
        expected: verify query result
        """

        half = ct.default_nb // 2
        collection_w, partition_w, df_partition, df_default = self.insert_entities_into_two_partitions_in_half(half)

        int_values = df_default[ct.default_int64_field_name].values.tolist()
        term_expr = f'{ct.default_int64_field_name} in {int_values}'
        res, _ = collection_w.query(term_expr)
        assert len(res) == len(int_values)

    @pytest.mark.tags(CaseLabel.L1)
    def test_query_expr_repeated_term_array(self):
        """
        target: test query with repeated term array on primary field with unique value
        method: query with repeated array value
        expected: return hit entities, no repeated
        """
        collection_w, vectors, binary_raw_vectors = self.init_collection_general(prefix, insert_data=True)[0:3]
        int_values = [0, 0, 0, 0]
        term_expr = f'{ct.default_int64_field_name} in {int_values}'
        res, _ = collection_w.query(term_expr)
        assert len(res) == 1
        assert res[0][ct.default_int64_field_name] == int_values[0]

    @pytest.mark.tags(CaseLabel.L1)
    def test_query_dup_ids_dup_term_array(self):
        """
        target: test query on duplicate primary keys with dup term array
        method: 1.create collection and insert dup primary keys
                2.query with dup term array
        expected: todo
        """
        collection_w = self.init_collection_wrap(name=cf.gen_unique_str(prefix))
        df = cf.gen_default_dataframe_data(nb=100)
        df[ct.default_int64_field_name] = 0
        mutation_res, _ = collection_w.insert(df)
        assert mutation_res.primary_keys == df[ct.default_int64_field_name].tolist()
        collection_w.create_index(ct.default_float_vec_field_name, index_params=ct.default_flat_index)
        collection_w.load()
        term_expr = f'{ct.default_int64_field_name} in {[0, 0, 0]}'
        res = df.iloc[:, :2].to_dict('records')
        collection_w.query(term_expr, output_fields=["*"], check_items=CheckTasks.check_query_results,
                           check_task={exp_res: res})

    @pytest.mark.tags(CaseLabel.L0)
    def test_query_after_index(self):
        """
        target: test query after creating index
        method: 1. indexing
                2. load
                3. query
        expected: query result is correct
        """
        collection_w, vectors, binary_raw_vectors = self.init_collection_general(prefix, insert_data=True, is_index=True)[0:3]

        default_field_name = ct.default_float_vec_field_name
        collection_w.create_index(default_field_name, default_index_params)

        collection_w.load()

        int_values = [0]
        term_expr = f'{ct.default_int64_field_name} in {int_values}'
        check_vec = vectors[0].iloc[:, [0]][0:len(int_values)].to_dict('records')
        collection_w.query(term_expr, check_task=CheckTasks.check_query_results, check_items={exp_res: check_vec})

    @pytest.mark.tags(CaseLabel.L1)
    def test_query_after_search(self):
        """
        target: test query after search
        method: 1. search
                2. query without load again
        expected: query result is correct
        """

        limit = 1000
        nb_old = 500
        collection_w, vectors, binary_raw_vectors, insert_ids = \
            self.init_collection_general(prefix, True, nb_old)[0:4]

        # 2. search for original data after load
        vectors_s = [[random.random() for _ in range(ct.default_dim)] for _ in range(ct.default_nq)]
        collection_w.search(vectors_s[:ct.default_nq], ct.default_float_vec_field_name,
                            ct.default_search_params, limit, "int64 >= 0",
                            check_task=CheckTasks.check_search_results,
                            check_items={"nq": ct.default_nq, "limit": nb_old, "ids": insert_ids})

        # check number of entities and that method calls the flush interface
        assert collection_w.num_entities == nb_old

        term_expr = f'{ct.default_int64_field_name} in [0, 1]'
        check_vec = vectors[0].iloc[:, [0]][0:2].to_dict('records')
        collection_w.query(term_expr, check_task=CheckTasks.check_query_results, check_items={exp_res: check_vec})

    @pytest.mark.tags(CaseLabel.L1)
    def test_query_output_vec_field_after_index(self):
        """
        target: test query output vec field after index
        method: create index and specify vec field as output field
        expected: return primary field and vec field
        """
        collection_w = self.init_collection_wrap(name=cf.gen_unique_str(prefix))
        df = cf.gen_default_dataframe_data(nb=5000)
        collection_w.insert(df)
        assert collection_w.num_entities == 5000
        fields = [ct.default_int64_field_name, ct.default_float_vec_field_name]
        collection_w.create_index(ct.default_float_vec_field_name, default_index_params)
        assert collection_w.has_index()[0]
        res = df.loc[:1, [ct.default_int64_field_name, ct.default_float_vec_field_name]].to_dict('records')
        collection_w.load()
        collection_w.query(default_term_expr, output_fields=fields,
                           check_task=CheckTasks.check_query_results,
                           check_items={exp_res: res, "with_vec": True})

    @pytest.mark.tags(CaseLabel.L1)
    def test_query_output_binary_vec_field_after_index(self):
        """
        target: test query output vec field after index
        method: create index and specify vec field as output field
        expected: return primary field and vec field
        """
        collection_w, vectors = self.init_collection_general(prefix, insert_data=True, is_binary=True, is_index=True)[0:2]
        fields = [ct.default_int64_field_name, ct.default_binary_vec_field_name]
        collection_w.create_index(ct.default_binary_vec_field_name, binary_index_params)
        assert collection_w.has_index()[0]
        collection_w.load()
        res, _ = collection_w.query(default_term_expr, output_fields=[ct.default_binary_vec_field_name])
        assert res[0].keys() == set(fields)

    @pytest.mark.tags(CaseLabel.L2)
    def test_query_partition_repeatedly(self):
        """
        target: test query repeatedly on partition
        method: query on partition twice
        expected: verify query result
        """

        # create connection
        self._connect()

        # init collection
        collection_w = self.init_collection_wrap(name=cf.gen_unique_str(prefix))

        # init partition
        partition_w = self.init_partition_wrap(collection_wrap=collection_w)

        # insert data to partition
        df = cf.gen_default_dataframe_data()
        partition_w.insert(df)

        # check number of entities and that method calls the flush interface
        assert collection_w.num_entities == ct.default_nb

        # load partition
        collection_w.create_index(ct.default_float_vec_field_name, index_params=ct.default_flat_index)
        partition_w.load()

        # query twice
        res_one, _ = collection_w.query(default_term_expr, partition_names=[partition_w.name])
        res_two, _ = collection_w.query(default_term_expr, partition_names=[partition_w.name])
        assert res_one == res_two

    @pytest.mark.tags(CaseLabel.L2)
    def test_query_another_partition(self):
        """
        target: test query another partition
        method: 1. insert entities into two partitions
                2.query on one partition and query result empty
        expected: query result is empty
        """
        half = ct.default_nb // 2
        collection_w, partition_w, _, _ = self.insert_entities_into_two_partitions_in_half(half)

        term_expr = f'{ct.default_int64_field_name} in [{half}]'
        # half entity in _default partition rather than partition_w
        collection_w.query(term_expr, partition_names=[partition_w.name], check_task=CheckTasks.check_query_results,
                           check_items={exp_res: []})

    @pytest.mark.tags(CaseLabel.L1)
    def test_query_multi_partitions_multi_results(self):
        """
        target: test query on multi partitions and get multi results
        method: 1.insert entities into two partitions
                2.query on two partitions and query multi result
        expected: query results from two partitions
        """
        half = ct.default_nb // 2
        collection_w, partition_w, _, _ = self.insert_entities_into_two_partitions_in_half(half)

        term_expr = f'{ct.default_int64_field_name} in [{half - 1}, {half}]'
        # half entity in _default, half-1 entity in partition_w
        res, _ = collection_w.query(term_expr, partition_names=[ct.default_partition_name, partition_w.name])
        assert len(res) == 2

    @pytest.mark.tags(CaseLabel.L2)
    def test_query_multi_partitions_single_result(self):
        """
        target: test query on multi partitions and get single result
        method: 1.insert into two partitions
                2.query on two partitions and query single result
        expected: query from two partitions and get single result
        """
        half = ct.default_nb // 2
        collection_w, partition_w, df_partition, df_default = self.insert_entities_into_two_partitions_in_half(half)

        term_expr = f'{ct.default_int64_field_name} in [{half}]'
        # half entity in _default
        res, _ = collection_w.query(term_expr, partition_names=[ct.default_partition_name, partition_w.name])
        assert len(res) == 1
        assert res[0][ct.default_int64_field_name] == half

    @pytest.mark.tags(CaseLabel.L1)
    def test_query_growing_segment_data(self):
        """
        target: test query data in the growing segment
        method: 1. create collection
                2.load collection
                3.insert without flush
                4.query
        expected: Data can be queried
        """
        import time
        collection_w = self.init_collection_wrap(name=cf.gen_unique_str(prefix))
        # load collection
        collection_w.create_index(ct.default_float_vec_field_name, index_params=ct.default_flat_index)
        collection_w.load()
        tmp_nb = 100
        df = cf.gen_default_dataframe_data(tmp_nb)
        collection_w.insert(df)

        res = df.iloc[1:2, :1].to_dict('records')
        time.sleep(1)
        collection_w.query(f'{ct.default_int64_field_name} in [1]',
                           check_task=CheckTasks.check_query_results, check_items={exp_res: res})


class TestqueryString(TestcaseBase):
    """
    ******************************************************************
      The following cases are used to test query with string
    ******************************************************************
    """

    @pytest.mark.tags(CaseLabel.L1)
    def test_query_string_is_not_primary(self):
        """
        target: test query data with string field is not primary
        method: create collection and insert data
                collection.load()
                query with string expr in string field is not primary
        expected: query successfully
        """

        collection_w, vectors = self.init_collection_general(prefix, insert_data=True)[0:2]
        res = vectors[0].iloc[:2, :3].to_dict('records')
        output_fields = [default_float_field_name, default_string_field_name]
        collection_w.query(default_string_term_expr, output_fields=output_fields,
                           check_task=CheckTasks.check_query_results, check_items={exp_res: res})

    @pytest.mark.tags(CaseLabel.L1)
    @pytest.mark.parametrize("expression", cf.gen_normal_string_expressions(default_string_field_name))
    def test_query_string_is_primary(self, expression):
        """
        target: test query with output field only primary field
        method: specify string primary field as output field
        expected: return string primary field
        """
        collection_w, vectors = self.init_collection_general(prefix, insert_data=True, primary_field=ct.default_string_field_name)[0:2]
        res, _ = collection_w.query(expression, output_fields=[ct.default_string_field_name])
        assert res[0].keys() == {ct.default_string_field_name}

    @pytest.mark.tags(CaseLabel.L1)
    def test_query_string_with_mix_expr(self):
        """
        target: test query data
        method: create collection and insert data
                query with mix expr in string field and int field
        expected: query successfully
        """
        collection_w, vectors = self.init_collection_general(prefix, insert_data=True, primary_field=ct.default_string_field_name)[0:2]
        res = vectors[0].iloc[:, 1:3].to_dict('records')
        output_fields = [default_float_field_name, default_string_field_name]
        collection_w.query(default_mix_expr, output_fields=output_fields,
                                   check_task=CheckTasks.check_query_results, check_items={exp_res: res})

    @pytest.mark.tags(CaseLabel.L1)
    @pytest.mark.parametrize("expression", cf.gen_invaild_string_expressions())
    def test_query_with_invalid_string_expr(self, expression):
        """
        target: test query data
        method: create collection and insert data
                query with invalid expr
        expected: Raise exception
        """
        collection_w = self.init_collection_general(prefix, insert_data=True)[0]
        collection_w.query(expression, check_task=CheckTasks.err_res,
                           check_items={ct.err_code: 1, ct.err_msg: "type mismatch"})

    @pytest.mark.tags(CaseLabel.L1)
    def test_query_string_expr_with_binary(self):
        """
        target: test query string expr with binary
        method: query string expr with binary
        expected: verify query successfully
        """
        collection_w, vectors= self.init_collection_general(prefix, insert_data=True, is_binary=True, is_index=True)[0:2]
        collection_w.create_index(ct.default_binary_vec_field_name, binary_index_params)
        collection_w.load()
        assert collection_w.has_index()[0]
        res, _ = collection_w.query(default_string_term_expr, output_fields=[ct.default_binary_vec_field_name])
        assert len(res) == 2

    @pytest.mark.tags(CaseLabel.L1)
    def test_query_string_expr_with_prefixes(self):
        """
        target: test query with prefix string expression
        method: specify string is primary field, use prefix string expr
        expected: verify query successfully
        """
        collection_w, vectors = self.init_collection_general(prefix, insert_data=True, primary_field=ct.default_string_field_name)[0:2]
        res = vectors[0].iloc[:1, :3].to_dict('records')
        expression = 'varchar like "0%"'
        output_fields = [default_int_field_name, default_float_field_name, default_string_field_name]
        collection_w.query(expression, output_fields=output_fields,
                           check_task=CheckTasks.check_query_results, check_items={exp_res: res})

    @pytest.mark.tags(CaseLabel.L1)
    def test_query_string_with_invaild_prefix_expr(self):
        """
        target: test query with invalid prefix string expression
        method: specify string primary field, use invaild prefix string expr
        expected: raise error
        """
        collection_w = self.init_collection_general(prefix, insert_data=True)[0]
        expression = 'float like "0%"'
        collection_w.query(expression, check_task=CheckTasks.err_res,
                           check_items={ct.err_code: 1, ct.err_msg: "like operation on non-string field is unsupported"}
                           )

    @pytest.mark.tags(CaseLabel.L1)
    def test_query_compare_two_fields(self):
        """
        target: test query with bool expression comparing two fields
        method: specify string primary field, compare two fields
        expected: verify query successfully
        """
        collection_w = self.init_collection_general(prefix, insert_data=True, primary_field=ct.default_string_field_name)[0]
        res = []
        expression = 'float > int64'
        output_fields = [default_int_field_name, default_float_field_name, default_string_field_name]
        collection_w.query(expression, output_fields=output_fields,
                           check_task=CheckTasks.check_query_results, check_items={exp_res: res})

    @pytest.mark.tags(CaseLabel.L1)
    def test_query_compare_invalid_fields(self):
        """
        target: test query with
        method: specify string primary field, compare string and int field
        expected: raise error
        """
        collection_w = self.init_collection_general(prefix, insert_data=True, primary_field=ct.default_string_field_name)[0]
        expression = 'varchar == int64'
        collection_w.query(expression, check_task=CheckTasks.err_res,
                           check_items={ct.err_code: 1, ct.err_msg: f' cannot parse expression:{expression}'})

    @pytest.mark.tags(CaseLabel.L1)
    def test_query_after_insert_multi_threading(self):
        """
        target: test data consistency after multi threading insert
        method: multi threads insert, and query, compare queried data with original
        expected: verify data consistency
        """
        collection_w = self.init_collection_wrap(name=cf.gen_unique_str(prefix))
        thread_num = 4
        threads = []
        primary_keys = []
        df_list = []

        #prepare original data for parallel insert
        for i in range(thread_num):
            df = cf.gen_default_dataframe_data(ct.default_nb, start=i*ct.default_nb)
            df_list.append(df)
            primary_key = df[ct.default_int64_field_name].values.tolist()
            primary_keys.append(primary_key)

        def insert(thread_i):
            log.debug(f'In thread-{thread_i}')
            mutation_res, _ = collection_w.insert(df_list[thread_i])
            assert mutation_res.insert_count == ct.default_nb
            assert mutation_res.primary_keys == primary_keys[thread_i]

        for i in range(thread_num):
            x = threading.Thread(target=insert, args=(i,))
            threads.append(x)
            x.start()
        for t in threads:
            t.join()
        assert collection_w.num_entities == ct.default_nb * thread_num

        #Check data consistency after parallel insert
        collection_w.create_index(ct.default_float_vec_field_name, index_params=ct.default_flat_index)
        collection_w.load()
        df_dict_list = []
        for df in df_list:
            df_dict_list += df.to_dict('records')
        output_fields = ["*", "%"]
        expression = "int64 >= 0"
        collection_w.query(expression, output_fields=output_fields,
                           check_task=CheckTasks.check_query_results,
                           check_items={exp_res: df_dict_list,
                                        "primary_field": default_int_field_name,
                                        "with_vec": True})

    @pytest.mark.tags(CaseLabel.L2)
    def test_query_string_field_pk_is_empty(self):
        """
        target: test query with string expr and string field is primary
        method: create collection , string field is primary
                collection load and insert empty data with string field
                collection query uses string expr in string field
        expected: query successfully
        """
        # 1. create a collection
        schema = cf.gen_string_pk_default_collection_schema()
        collection_w = self.init_collection_wrap(cf.gen_unique_str(prefix), schema=schema)
        collection_w.create_index(ct.default_float_vec_field_name, index_params=ct.default_flat_index)
        collection_w.load()
        
        nb = 3000
        df = cf.gen_default_list_data(nb)
        df[2] = [""for _ in range(nb)] 

        collection_w.insert(df)
        assert collection_w.num_entities == nb

        
        string_exp = "varchar >= \"\""
        output_fields = [default_int_field_name, default_float_field_name, default_string_field_name]
        res, _ = collection_w.query(string_exp, output_fields=output_fields)

        assert len(res) == 1

    @pytest.mark.tags(CaseLabel.L2)
    def test_query_string_field_not_primary_is_empty(self):
        """
        target: test query with string expr and string field is not primary
        method: create collection , string field is primary
                collection load and insert empty data with string field
                collection query uses string expr in string field
        expected: query successfully
        """
        # 1.  create a collection
        collection_w, vectors = self.init_collection_general(prefix, insert_data=False, is_index=True)[0:2]
        
        nb = 3000
        df = cf.gen_default_list_data(nb)
        df[2] = [""for _ in range(nb)] 

        collection_w.insert(df)
        assert collection_w.num_entities == nb
        
        collection_w.create_index(ct.default_float_vec_field_name, default_index_params)
        assert collection_w.has_index()[0]
        collection_w.load()
        
        output_fields = [default_int_field_name, default_float_field_name, default_string_field_name]
        
        expr = "varchar == \"\""
        res, _ = collection_w.query(expr, output_fields=output_fields)

        assert len(res) == nb
    
    @pytest.mark.tags(CaseLabel.L2)
    def test_query_with_create_diskann_index(self):
        """
        target: test query after create diskann index 
        method: create a collection and build diskann index 
        expected: verify query result
        """
        collection_w, vectors = self.init_collection_general(prefix, insert_data=True, is_index=True)[0:2]
    
        collection_w.create_index(ct.default_float_vec_field_name, ct.default_diskann_index)
        assert collection_w.has_index()[0]

        collection_w.load()

        int_values = [0]
        term_expr = f'{ct.default_int64_field_name} in {int_values}'
        check_vec = vectors[0].iloc[:, [0]][0:len(int_values)].to_dict('records')
        collection_w.query(term_expr, check_task=CheckTasks.check_query_results, check_items={exp_res: check_vec})
    
    @pytest.mark.tags(CaseLabel.L2)
    def test_query_with_create_diskann_with_string_pk(self):
        """
        target: test query after create diskann index 
        method: create a collection with string pk and build diskann index 
        expected: verify query result
        """
        collection_w, vectors = self.init_collection_general(prefix, insert_data=True,  primary_field=ct.default_string_field_name, is_index=True)[0:2]
        collection_w.create_index(ct.default_float_vec_field_name, ct.default_diskann_index)
        assert collection_w.has_index()[0]
        collection_w.load()
        res = vectors[0].iloc[:, 1:3].to_dict('records')
        output_fields = [default_float_field_name, default_string_field_name]
        collection_w.query(default_mix_expr, output_fields=output_fields,
                                   check_task=CheckTasks.check_query_results, check_items={exp_res: res})
        
