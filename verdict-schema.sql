CREATE TABLE function (
    id integer primary key autoincrement,
    fully_qualified_name text not null
);
CREATE TABLE function_property_pair (
    function integer not null,
    property_hash text not null,
    foreign key(function) references function(id),
    foreign key(property_hash) references property(hash),
    primary key(function, property_hash)
);
CREATE TABLE property (
    hash text primary key,
    serialised_structure text not null,
    index_in_specification_file integer not null
);
CREATE TABLE binding (
    id integer primary key autoincrement,
    binding_space_index int not null,
    function int not null,
    property_hash text not null,
    binding_statement_lines text not null,
    foreign key(function) references function(id)
);
CREATE TABLE function_call (
    id integer primary key autoincrement,
    function int not null,
    time_of_call timestamp not null,
    end_time_of_call timestamp not null,
    trans int not null,
    path_condition_id_sequence text not null,
    foreign key(function) references function(id),
    foreign key(trans) references trans(id)
);
CREATE TABLE test_data (
    id integer primary key autoincrement,
    test_name text,
    test_result text,
    start_time timestamp,
    end_time timestamp
);
CREATE TABLE verdict (
    id integer not null primary key autoincrement,
    binding int not null,
    verdict int not null,
    time_obtained timestamp not null,
    function_call int not null,
    collapsing_atom int not null,
    collapsing_atom_sub_index int not null,
    foreign key(binding) references binding(id),
    foreign key(function_call) references function_call(id)
);
CREATE TABLE trans (
    id integer primary key autoincrement,
    time_of_transaction timestamp not null
);
CREATE TABLE atom (
    id integer not null primary key autoincrement,
    property_hash text not null,
    serialised_structure text not null,
    index_in_atoms int not null,
    foreign key(property_hash) references property(hash)
);
CREATE TABLE atom_instrumentation_point_pair (
    atom int not null,
    instrumentation_point int not null,
    primary key(atom, instrumentation_point),
    foreign key(atom) references atom(id),
    foreign key(instrumentation_point) references instrumentation_point(id)
);
CREATE TABLE binding_instrumentation_point_pair (
    binding int not null,
    instrumentation_point int not null,
    primary key(binding, instrumentation_point),
    foreign key(binding) references binding(id),
    foreign key(instrumentation_point) references instrumentation_point(id)
);
CREATE TABLE instrumentation_point (
    id integer not null primary key autoincrement,
    serialised_condition_sequence text not null,
    reaching_path_length int not null
);
CREATE TABLE observation (
    id integer not null primary key autoincrement,
    instrumentation_point int not null,
    verdict int not null,
    observed_value text not null,
    observation_time timestamp not null,
    observation_end_time timestamp not null,
    atom_index int not null,
    sub_index int not null,
    previous_condition_offset integer not null,
    foreign key(instrumentation_point) references instrumentation_point(id),
    foreign key(verdict) references verdict(id)
);
CREATE TABLE observation_assignment_pair (
    observation int not null,
    assignment int not null,
    primary key(observation, assignment),
    foreign key(observation) references observation(id),
    foreign key(assignment) references assignment(id)
);
CREATE TABLE assignment (
    id integer not null primary key autoincrement,
    variable text not null,
    value text not null,
    type text not null
);
CREATE TABLE path_condition_structure (
    id integer not null primary key autoincrement,
    serialised_condition text not null
);
CREATE TABLE plot (
    hash text not null primary key,
    description text not null,
    data text not null,
    creation_time timestamp not null
);