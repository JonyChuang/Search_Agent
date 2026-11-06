package com.searchagent.career.job;

import java.util.List;

import org.apache.ibatis.annotations.Delete;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

@Mapper
interface JobMapper {
    String COLUMNS = "id, company, title, location, description, source_name, source_url, sourced_on";

    @Select("SELECT " + COLUMNS + " FROM career_job WHERE user_id = #{userId} ORDER BY created_at DESC, id DESC")
    List<JobService.Entry> list(String userId);

    @Select("SELECT " + COLUMNS + " FROM career_job WHERE user_id = #{userId} AND id = #{id}")
    JobService.Entry find(@Param("userId") String userId, @Param("id") String id);

    @Insert("""
            INSERT INTO career_job (user_id, id, company, title, location, description, source_name, source_url, sourced_on)
            VALUES (#{userId}, #{id},
                #{entry.company}, #{entry.title}, #{entry.location}, #{entry.description}, #{entry.sourceName}, #{entry.sourceUrl}, #{entry.sourcedOn})
            """)
    void insert(@Param("userId") String userId, @Param("id") String id, @Param("entry") JobService.Input entry);

    @Update("""
            UPDATE career_job
            SET company = #{entry.company}, title = #{entry.title}, location = #{entry.location},
                description = #{entry.description}, source_name = #{entry.sourceName}, source_url = #{entry.sourceUrl},
                sourced_on = #{entry.sourcedOn}
            WHERE user_id = #{userId} AND id = #{id}
            """)
    void update(@Param("userId") String userId, @Param("id") String id, @Param("entry") JobService.Input entry);

    @Delete("DELETE FROM career_job WHERE user_id = #{userId} AND id = #{id}")
    int delete(@Param("userId") String userId, @Param("id") String id);
}
